<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import {
  api,
  type VpaAnalysisResult,
  type VpaSampleMeta,
  type VpaCodexPayload,
  type VpaHealthPayload,
  type VpaTimeframeOption,
  type VpaLevel,
  type VpaEvidenceItem,
  type VpaCongestionPattern,
  type VpaBar,
  readVpa,
  buildRiskLadder,
  type VpaRead,
  type VpaRiskLadder,
} from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import { useChartSize } from '@/composables/useChartSize'
import { linearScale, niceTicks, candlePath, type CandleBar } from '@/charts'

interface ChartBar extends VpaBar {
  live?: boolean
}

const LOOKBACKS = [
  { value: 60, label: '60' },
  { value: 120, label: '120' },
  { value: 250, label: '250' },
  { value: 500, label: '500' },
] as const

/** Cap so recent candles stay wide enough to read; engine still sees the full lookback. */
const MAX_CHART_BARS = 160

/** Every absent number renders as this. Never a plausible-looking constant. */
const DASH = '—'

// State
const ingestionMode = ref<'symbol' | 'screenshot'>('symbol')
const analyzing = ref(false)
const fetchingTrajectory = ref(false)
const errorMsg = ref<string | null>(null)
const currentImage = ref<string | null>(null)
const symbolInput = ref('NVDA')
const timeframeInput = ref('1D')
const lookbackBars = ref<number>(120)
const assetClassInput = ref('equities')
const notesInput = ref('')
const analysisResult = ref<VpaAnalysisResult | null>(null)
/** Receipt for the scan button: when it last ran, and whether the read moved. */
const lastScanAt = ref<Date | null>(null)
const lastScanChanged = ref<boolean | null>(null)
const sampleList = ref<VpaSampleMeta[]>([])
const codex = ref<VpaCodexPayload | null>(null)
const codexDrawerOpen = ref(false)
const selectedTab = ref<'analysis' | 'scenarios' | 'execution'>('analysis')
const isDragging = ref(false)

// Capability report — drives the timeframe dropdown and the vision button.
const health = ref<VpaHealthPayload | null>(null)
const healthLoading = ref(false)
const healthError = ref<string | null>(null)
const timeframeNote = ref<string | null>(null)

// Equity Trajectory Data & Chart
const equityBars = ref<ChartBar[]>([])
const hostRef = ref<HTMLDivElement | null>(null)
const chartSvg = ref<SVGSVGElement | null>(null)
const { W, H } = useChartSize(hostRef, { minW: 480, minH: 380, fallbackW: 980, fallbackH: 440 })
const hoveredBar = ref<{ bar: ChartBar; x: number; y: number; idx: number } | null>(null)
const hoveredLevelKey = ref<string | null>(null)
const selectedEvidenceIdx = ref<number | null>(null)

const popularEquities = ['NVDA', 'AAPL', 'TSLA', 'SPY', 'QQQ', 'MSFT', 'AMZN', 'GOOGL']

const assetClasses = [
  { value: 'equities', label: 'US Equities' },
  { value: 'options', label: 'Options Flow' },
  { value: 'futures', label: 'Index / Commodity Futures' },
  { value: 'forex', label: 'Spot Forex' },
  { value: 'crypto', label: 'Crypto' },
]

/* ------------------------------------------------------------ capability */

/**
 * Timeframe options come from `GET /api/vpa/health` (contract §4), never from a
 * hardcoded array. Unbacked timeframes arrive with `available: false` and a
 * reason and are rendered disabled — the old build silently served daily bars
 * under a 15m label (defect D1).
 */
const timeframeOptions = computed<VpaTimeframeOption[]>(() => health.value?.timeframes ?? [])
const capabilityKnown = computed(() => timeframeOptions.value.length > 0)
const selectedTimeframe = computed<VpaTimeframeOption | null>(
  () => timeframeOptions.value.find((t) => t.value === timeframeInput.value) ?? null,
)
const timeframeLabel = computed(() => selectedTimeframe.value?.label ?? timeframeInput.value)
const unavailableTimeframes = computed(() => timeframeOptions.value.filter((t) => !t.available))

/**
 * When the capability probe answers, the server owns bar loading for the
 * requested timeframe (`research/vpa_bars.load_bars`). Until then we are talking
 * to the legacy handler, which can only read bars the browser sends it — daily
 * ones, from `/api/trajectory`. We say which mode we are in rather than pretend.
 */
const serverLoadsBars = computed(() => capabilityKnown.value)

/**
 * Availability is per symbol, not global. 59 symbols carry hourly bars but 589
 * carry daily, so offering 1h for a daily-only ticker means the user picks it
 * and only learns it was downgraded once the response lands.
 */
async function loadHealth(): Promise<void> {
  healthLoading.value = true
  healthError.value = null
  try {
    const res = await api.vpaHealth(symbolInput.value)
    health.value = res && Array.isArray(res.timeframes) ? res : null
    if (!health.value) {
      healthError.value = 'capability report returned no timeframe matrix'
    }
    reconcileTimeframe()
  } catch (err: unknown) {
    health.value = null
    healthError.value = err instanceof Error ? err.message : 'capability probe failed'
  } finally {
    healthLoading.value = false
  }
}

/** Keep the selection inside what the server can actually serve — and say so. */
function reconcileTimeframe(): void {
  const opts = timeframeOptions.value
  if (opts.length === 0) return
  const current = opts.find((o) => o.value === timeframeInput.value)
  if (current?.available) {
    timeframeNote.value = null
    return
  }
  const firstAvailable = opts.find((o) => o.available)
  if (!firstAvailable) {
    timeframeNote.value = 'The server reports no timeframe with bars on disk.'
    return
  }
  const previous = timeframeInput.value
  suppressParamWatch = true
  timeframeInput.value = firstAvailable.value
  timeframeNote.value = `"${previous}" is not served by this deployment — selected ${firstAvailable.label}.`
  void nextTick(() => {
    suppressParamWatch = false
  })
}

/* ------------------------------------------------------------- vision */

const visionStatus = computed(() => analysisResult.value?.vision_status ?? null)

/** `null` means genuinely unknown — neither the health probe nor a response said. */
const visionAvailable = computed<boolean | null>(() => {
  if (visionStatus.value && typeof visionStatus.value.available === 'boolean') {
    return visionStatus.value.available
  }
  if (health.value?.vision && typeof health.value.vision.available === 'boolean') {
    return health.value.vision.available
  }
  return null
})

const visionReason = computed<string | null>(
  () => visionStatus.value?.reason ?? health.value?.vision?.reason ?? null,
)

/** The exact D2 failure: the image went up the wire and was thrown away. */
const visionDroppedImage = computed(
  () => !!visionStatus.value?.image_received && visionStatus.value?.image_used === false,
)

const snapBlockedReason = computed<string | null>(() => {
  if (equityBars.value.length === 0) return 'Load a symbol first: there is no chart to snapshot.'
  if (visionAvailable.value === null) {
    return 'Chart-vision capability unknown: GET /api/vpa/health is not answering.'
  }
  if (visionAvailable.value === false) {
    return visionReason.value || 'Chart vision is not configured on this server.'
  }
  return null
})
const snapDisabled = computed(() => analyzing.value || snapBlockedReason.value !== null)

/* --------------------------------------------------------- derived reads */

const vpaRead = computed<VpaRead | null>(() => readVpa(analysisResult.value))

const barsMeta = computed(() => analysisResult.value?.bars_meta ?? null)
const downgraded = computed(() => barsMeta.value?.downgraded === true)

/** The canvas paints `/api/trajectory` daily bars; the engine may have used others. */
const chartServedMismatch = computed(() => {
  if (analysisResult.value?.bars && analysisResult.value.bars.length > 0) return false
  const served = barsMeta.value?.timeframe_served
  if (!served || equityBars.value.length === 0) return false
  return !/^(1d|daily|d)$/i.test(served)
})

const levels = computed<VpaLevel[]>(() =>
  Array.isArray(analysisResult.value?.levels) ? analysisResult.value!.levels! : [],
)
const orderedLevels = computed(() => [...levels.value].sort((a, b) => b.price - a.price))
const vap = computed(() => analysisResult.value?.vap ?? null)
const hasVap = computed(
  () =>
    !!vap.value &&
    (typeof vap.value.poc === 'number' ||
      (Array.isArray(vap.value.bins) && vap.value.bins.length > 0)),
)

const evidence = computed<VpaEvidenceItem[]>(() =>
  Array.isArray(analysisResult.value?.evidence) ? analysisResult.value!.evidence! : [],
)
const orderedEvidence = computed(() =>
  [...evidence.value].sort((a, b) => Math.abs(b.weight ?? 0) - Math.abs(a.weight ?? 0)),
)
const maxEvidenceWeight = computed(() =>
  evidence.value.reduce((m, e) => Math.max(m, Math.abs(e.weight ?? 0)), 0),
)
const probabilityBasis = computed(() => analysisResult.value?.probability_basis ?? null)

/* --- Ch.8 dynamic trend line. `direction: 'none'` is a real, reportable read
   (two-sided pivots), so it is rendered rather than hidden. */
const dynamicTrend = computed(() => analysisResult.value?.dynamic_trend ?? null)
const hasDynamicTrend = computed(() => !!dynamicTrend.value?.direction)

/* --- Ch.11 congestion geometry. */
const congestionPatterns = computed<VpaCongestionPattern[]>(() =>
  Array.isArray(analysisResult.value?.congestion_patterns)
    ? analysisResult.value!.congestion_patterns!
    : [],
)

/* --- The arithmetic behind the confidence headline, so it is auditable.
   Only the multiplier components go in the bar list; the two raw counts
   (bar_count, data_age_days) are read-outs, not 0..1 factors. */
const CONFIDENCE_COMPONENT_LABELS: Record<string, string> = {
  coverage: 'Bar coverage',
  agreement: 'Evidence agreement',
  recency: 'Data recency',
  evidence_density: 'Evidence density',
  downgrade_penalty: 'Downgrade penalty',
  method_ceiling: 'Method ceiling',
}
const confidenceBasis = computed(() => analysisResult.value?.confidence_basis ?? null)
const confidenceComponents = computed(() => {
  const c = confidenceBasis.value?.components
  if (!c) return []
  return Object.entries(CONFIDENCE_COMPONENT_LABELS)
    .map(([key, label]) => ({ key, label, value: (c as Record<string, number | undefined>)[key] }))
    .filter((row) => typeof row.value === 'number' && Number.isFinite(row.value))
})
const confidenceBarCount = computed(() => confidenceBasis.value?.components?.bar_count ?? null)
const confidenceDataAge = computed(() => confidenceBasis.value?.components?.data_age_days ?? null)

/* --- Whether the detection thresholds came from the book spec or are defaults. */
const thresholdsStatus = computed(() => analysisResult.value?.thresholds_status ?? null)

const atr = computed<number | null>(() =>
  typeof analysisResult.value?.atr === 'number' ? analysisResult.value.atr : null,
)

const confidencePct = computed<number | null>(() => {
  const c = analysisResult.value?.confidence_score
  return typeof c === 'number' && Number.isFinite(c) ? Math.round(c * 100) : null
})

/* The engine returns the bare reward multiple as a number (2.12); vision and
   the canned cases return a pre-formatted string. Accepting only the string
   silently threw away every computed ratio and printed "not derivable" over a
   figure that had in fact been derived. */
const riskReward = computed<string>(() => {
  const rr = analysisResult.value?.trade_execution_guide?.risk_reward_ratio
  if (typeof rr === 'number' && Number.isFinite(rr) && rr > 0) return `1 : ${rr.toFixed(2)}`
  return typeof rr === 'string' && rr.trim().length > 0 ? rr : DASH
})

/* Entry/stop/target are reported together or not at all, so one guard covers
   the triplet. The two distances are derived here rather than re-sent. */
const hasTradeLevels = computed(() => {
  const g = analysisResult.value?.trade_execution_guide
  return (
    typeof g?.entry_price === 'number' &&
    typeof g?.stop_price === 'number' &&
    typeof g?.target_price === 'number'
  )
})
const tradeRiskPerUnit = computed<number | null>(() => {
  const g = analysisResult.value?.trade_execution_guide
  if (!hasTradeLevels.value) return null
  return Math.abs(g!.entry_price! - g!.stop_price!)
})
const tradeRewardPerUnit = computed<number | null>(() => {
  const g = analysisResult.value?.trade_execution_guide
  if (!hasTradeLevels.value) return null
  return Math.abs(g!.target_price! - g!.entry_price!)
})

const srMethod = computed(
  () => analysisResult.value?.forensic_breakdown?.support_resistance?.method ?? null,
)

/* A zone that has been both floor and ceiling is the Ch.7 house analogy in the
   data. `source` is "pivot_cluster" on every row and says nothing; `origins`
   says which side of the house the zone has actually been. */
function levelOriginLabel(l: VpaLevel): string {
  const origins = Array.isArray(l.origins) ? l.origins : l.origin ? [l.origin] : []
  if (origins.length > 1) return 'floor & ceiling'
  return origins[0] ? levelKindLabel(origins[0]) : DASH
}

/* Bars since the level was last touched — a band untouched for most of the
   window is history, not a live level. */
function levelBarsSinceTouch(l: VpaLevel): number | null {
  const total = barsMeta.value?.bar_count
  if (typeof l.last_touch_bar !== 'number' || typeof total !== 'number') return null
  return Math.max(0, total - 1 - l.last_touch_bar)
}

const scanStamp = computed(() =>
  lastScanAt.value ? lastScanAt.value.toTimeString().slice(0, 8) : DASH,
)

/**
 * Every path that lands a result goes through here. The engine is
 * deterministic: the same symbol, timeframe and bars return a byte-identical
 * read in ~30ms, so the spinner never paints and nothing on screen moves — the
 * scan button is indistinguishable from a broken one. Stamp each run and say
 * whether the read actually changed.
 *
 * Must be called by *all* analyse paths. Stamping only the button's own path
 * left the receipt asserting "unchanged" after a timeframe switch had in fact
 * changed the read.
 */
function applyResult(res: VpaAnalysisResult): void {
  const before = analysisResult.value ? JSON.stringify(analysisResult.value) : null
  analysisResult.value = res
  if (Array.isArray(res.bars) && res.bars.length > 0) {
    equityBars.value = res.bars.map(normalizeBar).filter((b): b is ChartBar => b !== null)
  }
  lastScanAt.value = new Date()
  lastScanChanged.value = before === null ? null : JSON.stringify(res) !== before
  selectedEvidenceIdx.value = null
}

const isReferenceCase = computed(() => analysisResult.value?.is_sample === true)

const scenarioProbabilitySum = computed<number | null>(() => {
  const res = analysisResult.value
  if (!res) return null
  const primary = res.primary_scenario?.probability_pct
  if (typeof primary !== 'number') return null
  const alts = (res.alternative_scenarios || []).reduce(
    (sum, a) => sum + (typeof a.probability_pct === 'number' ? a.probability_pct : 0),
    0,
  )
  return primary + alts
})

/* --------------------------------------------------------- formatters */

function fmtPrice(v?: number | null, dp = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? `$${v.toFixed(dp)}` : DASH
}
function fmtNum(v?: number | null, dp = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(dp) : DASH
}
function fmtInt(v?: number | null): string {
  return typeof v === 'number' && Number.isFinite(v) ? Math.round(v).toLocaleString() : DASH
}
function fmtPct(v?: number | null): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${Math.round(v)}%` : DASH
}
function fmtText(v?: string | null): string {
  return typeof v === 'string' && v.trim().length > 0 ? v : DASH
}
function fmtStamp(v?: string | null): string {
  if (!v) return DASH
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return v
  return v.includes('T') ? v.replace('T', ' ').slice(0, 16) : v.slice(0, 10)
}
function fmtBarDate(v?: string | null): string {
  if (!v) return DASH
  const s = v.replace('T', ' ')
  return s.length >= 16 ? s.slice(0, 16) : s.slice(0, 10)
}

function asNum(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim()) {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** Accept both the wire shape `{d,o,h,l,c,v}` and the engine/long shape `{date,open,...}`. */
function normalizeBar(raw: unknown): ChartBar | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const o = asNum(r.o ?? r.open)
  const h = asNum(r.h ?? r.high)
  const l = asNum(r.l ?? r.low)
  const c = asNum(r.c ?? r.close)
  if (o === null || h === null || l === null || c === null) return null
  const v = asNum(r.v ?? r.volume) ?? 0
  const d = String(r.d ?? r.date ?? '')
  return { d, o, h, l, c, v, live: r.live === true }
}
function levelKindLabel(kind: string): string {
  return /support/i.test(kind) ? 'Support' : /resist/i.test(kind) ? 'Resistance' : kind
}
function levelKey(l: VpaLevel, idx: number): string {
  return `${l.kind}:${l.price}:${idx}`
}

/* ------------------------------------------------------------ lifecycle */

onMounted(async () => {
  window.addEventListener('paste', handleGlobalPaste)
  try {
    const [samplesRes, codexRes] = await Promise.all([
      api.vpaSamples().catch(() => ({ samples: [] })),
      api.vpaCodex().catch(() => null),
      loadHealth(),
    ])
    sampleList.value = samplesRes.samples || []
    codex.value = codexRes

    // Load default equity on start
    if (symbolInput.value) {
      await fetchEquityDataAndAnalyze(symbolInput.value)
    }
  } catch (err: unknown) {
    console.warn('Failed to load initial VPA samples/codex:', err)
  }
})

onUnmounted(() => {
  window.removeEventListener('paste', handleGlobalPaste)
  if (paramReloadTimer) clearTimeout(paramReloadTimer)
})

// Paste listener
function handleGlobalPaste(e: ClipboardEvent): void {
  const items = e.clipboardData?.items
  if (!items) return
  for (let i = 0; i < items.length; i++) {
    if (items[i].type.indexOf('image') !== -1) {
      const file = items[i].getAsFile()
      if (file) {
        ingestionMode.value = 'screenshot'
        processImageFile(file)
        e.preventDefault()
        break
      }
    }
  }
}

// File drop & select handlers
function onFileSelected(e: Event): void {
  const target = e.target as HTMLInputElement
  if (target.files && target.files[0]) {
    ingestionMode.value = 'screenshot'
    processImageFile(target.files[0])
  }
}

function onDragOver(e: DragEvent): void {
  e.preventDefault()
  isDragging.value = true
}

function onDragLeave(): void {
  isDragging.value = false
}

function onDrop(e: DragEvent): void {
  e.preventDefault()
  isDragging.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files[0]) {
    ingestionMode.value = 'screenshot'
    processImageFile(e.dataTransfer.files[0])
  }
}

function processImageFile(file: File): void {
  const reader = new FileReader()
  reader.onload = (event) => {
    const rawDataUrl = event.target?.result as string
    if (rawDataUrl) {
      const img = new Image()
      img.onload = () => {
        const MAX_DIM = 1920
        let { width, height } = img
        if (width > MAX_DIM || height > MAX_DIM) {
          if (width > height) {
            height = Math.round((height * MAX_DIM) / width)
            width = MAX_DIM
          } else {
            width = Math.round((width * MAX_DIM) / height)
            height = MAX_DIM
          }
        }
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        if (ctx) {
          ctx.drawImage(img, 0, 0, width, height)
          const optimized = canvas.toDataURL('image/jpeg', 0.88)
          currentImage.value = optimized
          runAnalysis(optimized)
        } else {
          currentImage.value = rawDataUrl
          runAnalysis(rawDataUrl)
        }
      }
      img.onerror = () => {
        currentImage.value = rawDataUrl
        runAnalysis(rawDataUrl)
      }
      img.src = rawDataUrl
    }
  }
  reader.readAsDataURL(file)
}

// Fetch Equity OHLCV data & analyze
async function fetchEquityDataAndAnalyze(sym: string): Promise<void> {
  const cleanSym = (sym || symbolInput.value).trim().toUpperCase()
  if (!cleanSym) return

  const symbolChanged = symbolInput.value !== cleanSym
  symbolInput.value = cleanSym
  fetchingTrajectory.value = true
  analyzing.value = true
  errorMsg.value = null
  currentImage.value = null

  // Re-probe capability for THIS symbol before analysing, so the timeframe
  // dropdown reflects what this ticker can actually be served at.
  if (symbolChanged || !capabilityKnown.value) {
    await loadHealth()
  }

  try {
    const lookback = lookbackBars.value

    let res: VpaAnalysisResult
    if (serverLoadsBars.value) {
      // Direct server-side loading at requested timeframe — avoids redundant /api/trajectory fetch
      res = await api.vpaAnalyze({
        symbol: cleanSym,
        timeframe: timeframeInput.value,
        asset_class: assetClassInput.value,
        notes: notesInput.value || undefined,
        lookback,
      })
      // If server could not serve bars for this symbol, try client-side trajectory fallback
      if (
        (!res.bars || res.bars.length === 0) &&
        (!equityBars.value || equityBars.value.length === 0)
      ) {
        try {
          const traj = await api.trajectory(cleanSym, '6m', { includeQlib: false })
          const rawSeries = (traj?.series || [])
            .map(normalizeBar)
            .filter((b): b is ChartBar => b !== null)
          if (rawSeries.length > 0) {
            equityBars.value = rawSeries.slice(-lookback)
            res = await api.vpaAnalyze({
              symbol: cleanSym,
              timeframe: timeframeInput.value,
              asset_class: assetClassInput.value,
              notes: notesInput.value || undefined,
              lookback,
              ohlcv_series: equityBars.value,
            })
          }
        } catch {
          // trajectory fallback failed; keep the honest no-data response
        }
      }
    } else {
      // Legacy path: client supplies bars from /api/trajectory
      const traj = await api.trajectory(cleanSym, '6m', { includeQlib: false })
      const rawSeries = (traj?.series || [])
        .map(normalizeBar)
        .filter((b): b is ChartBar => b !== null)
      if (rawSeries.length === 0) {
        throw new Error(`No historical price bars returned for ${cleanSym}.`)
      }
      equityBars.value = rawSeries.slice(-lookback)
      res = await api.vpaAnalyze({
        symbol: cleanSym,
        timeframe: timeframeInput.value,
        asset_class: assetClassInput.value,
        notes: notesInput.value || undefined,
        lookback,
        ohlcv_series: equityBars.value,
      })
    }

    applyResult(res)
    await nextTick()
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : `Failed to load data for ${cleanSym}`
    errorMsg.value = msg
  } finally {
    fetchingTrajectory.value = false
    analyzing.value = false
  }
}

// Run screenshot / manual analysis
async function runAnalysis(imageBase64?: string): Promise<void> {
  const img = imageBase64 || currentImage.value
  if (!img && ingestionMode.value === 'screenshot') {
    errorMsg.value = 'Please paste or upload a chart screenshot first.'
    return
  }
  analyzing.value = true
  errorMsg.value = null

  try {
    const lookback = lookbackBars.value

    const sendBars = !serverLoadsBars.value && equityBars.value.length > 0
    const res = await api.vpaAnalyze({
      image_base64: img || undefined,
      symbol: symbolInput.value || undefined,
      timeframe: timeframeInput.value || undefined,
      asset_class: assetClassInput.value || undefined,
      notes: notesInput.value || undefined,
      lookback,
      ohlcv_series: sendBars ? equityBars.value : undefined,
    })
    applyResult(res)
    if (res.symbol && !symbolInput.value) {
      symbolInput.value = res.symbol
    }
    await nextTick()
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'VPA analysis failed'
    errorMsg.value = msg
  } finally {
    analyzing.value = false
  }
}

/**
 * Snapshot the rendered chart and send it for multimodal reading.
 * Refuses to run when `vision_status` says the capability is absent — the old
 * build posted the image into a void and reported success anyway (defect D2/D3).
 */
async function snapCanvasToVision(): Promise<void> {
  if (snapDisabled.value) return
  const svg = chartSvg.value
  if (!svg) return
  const xml = new XMLSerializer().serializeToString(svg)
  const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = () => reject(new Error('chart snapshot failed'))
      el.src = url
    })
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(W.value * 2))
    canvas.height = Math.max(1, Math.round(H.value * 2))
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--void').trim()
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    currentImage.value = canvas.toDataURL('image/png')
    ingestionMode.value = 'screenshot'
    await runAnalysis(currentImage.value)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * Stored reference cases are not a live read, so they
 * deliberately do not touch the live timeframe / asset-class controls.
 */
async function loadSample(sampleId: string): Promise<void> {
  analyzing.value = true
  errorMsg.value = null
  equityBars.value = []
  currentImage.value = null
  try {
    const res = await api.vpaAnalyze({ sample_id: sampleId })
    analysisResult.value = res
    // A textbook case is a transcription, not a scan of live bars. Clear the
    // receipt rather than stamping one over canned data.
    lastScanAt.value = null
    lastScanChanged.value = null
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'Failed to load sample'
    errorMsg.value = msg
  } finally {
    analyzing.value = false
  }
}

function clearChart(): void {
  currentImage.value = null
  equityBars.value = []
  analysisResult.value = null
  errorMsg.value = null
  notesInput.value = ''
  hoveredLevelKey.value = null
  hoveredBar.value = null
  selectedEvidenceIdx.value = null
}

/* ------------------------------------------------------------- chart */

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

const liveBar = computed<ChartBar | null>(() => {
  const raw = barsMeta.value?.live_bar
  return raw ? normalizeBar(raw) : null
})

/** Scored bars plus the forming candle (display-only). Oldest first. */
const chartBars = computed<ChartBar[]>(() => {
  const scored = equityBars.value
  const live = liveBar.value
  if (!live) return scored
  const last = scored[scored.length - 1]
  if (last && last.d === live.d) {
    return scored.map((b, i) => (i === scored.length - 1 ? { ...live } : b))
  }
  return [...scored, live]
})

const visibleStart = computed(() => Math.max(0, chartBars.value.length - MAX_CHART_BARS))
const visibleBars = computed(() => chartBars.value.slice(visibleStart.value))

const chartPad = { l: 10, r: 78, t: 12, b: 26 }
const volPane = 78
const gapPane = 10

const plotX0 = computed(() => chartPad.l)
const plotX1 = computed(() => Math.max(plotX0.value + 80, W.value - chartPad.r))
const profileW = computed(() => Math.max(36, Math.min(120, (plotX1.value - plotX0.value) * 0.18)))
/** Candles run to the right edge; the volume-at-price profile overlays them, same as the old canvas. */
const candleX1 = computed(() => plotX1.value - 4)
const priceY0 = computed(() => chartPad.t)
const priceY1 = computed(() =>
  Math.max(priceY0.value + 80, H.value - chartPad.b - volPane - gapPane),
)
const volY0 = computed(() => priceY1.value + gapPane)
const volY1 = computed(() => H.value - chartPad.b)

const priceDomain = computed<[number, number]>(() => {
  const vals: number[] = []
  for (const b of visibleBars.value) {
    vals.push(b.h, b.l)
  }
  for (const l of levels.value) {
    if (Number.isFinite(l.price)) vals.push(l.price)
    if (typeof l.low === 'number') vals.push(l.low)
    if (typeof l.high === 'number') vals.push(l.high)
  }
  const va = vap.value
  if (va) {
    for (const v of [va.poc, va.value_area_low, va.value_area_high]) {
      if (typeof v === 'number') vals.push(v)
    }
  }
  const g = analysisResult.value?.trade_execution_guide
  for (const v of [g?.entry_price, g?.stop_price, g?.target_price]) {
    if (typeof v === 'number') vals.push(v)
  }
  const finite = vals.filter((v) => Number.isFinite(v))
  if (!finite.length) return [0, 1]
  const lo = Math.min(...finite)
  const hi = Math.max(...finite)
  const padAmt = (hi - lo) * 0.04 || Math.abs(hi) * 0.001 || 1
  return [lo - padAmt, hi + padAmt]
})

const yScale = computed(() => linearScale(priceDomain.value, [priceY1.value, priceY0.value]))
const priceTicks = computed(() => niceTicks(priceDomain.value[0], priceDomain.value[1], 5))
const xScale = computed(() =>
  linearScale(
    [0, Math.max(visibleBars.value.length - 1, 1)],
    [plotX0.value + 4, candleX1.value - 4],
  ),
)

const candleHalfWidth = computed(() => {
  const n = Math.max(visibleBars.value.length, 1)
  return Math.max(0.7, Math.min(6, ((candleX1.value - plotX0.value) / n) * 0.32))
})

const candleGeom = computed(() => {
  const bars = visibleBars.value
  if (!bars.length) return { up: '', down: '', wicks: '' }
  const y = yScale.value
  const x = xScale.value
  const pts: CandleBar[] = bars.map((b, i) => ({
    x: x(i),
    o: y(b.o),
    h: y(b.h),
    l: y(b.l),
    c: y(b.c),
  }))
  return candlePath(pts, candleHalfWidth.value)
})

const volMax = computed(() => {
  const vols = visibleBars.value.map((b) => b.v)
  return Math.max(1, ...(vols.length ? vols : [1])) * 1.12
})
const volScaleY = computed(() => linearScale([0, volMax.value], [volY1.value, volY0.value]))

interface VolRect {
  x: number
  y: number
  w: number
  h: number
  up: boolean
  live: boolean
}
const volRects = computed<VolRect[]>(() => {
  const x = xScale.value
  const y = volScaleY.value
  const hw = candleHalfWidth.value
  const base = volY1.value
  return visibleBars.value.map((b, i) => {
    const top = y(b.v)
    return {
      x: x(i) - hw,
      y: top,
      w: hw * 2,
      h: Math.max(1, base - top),
      up: b.c >= b.o,
      live: b.live === true,
    }
  })
})

const volSmaPath = computed(() => {
  const bars = visibleBars.value
  if (bars.length < 2) return ''
  const vols = bars.map((b) => b.v)
  const sma: number[] = []
  for (let i = 0; i < vols.length; i++) {
    const start = Math.max(0, i - 19)
    const slice = vols.slice(start, i + 1)
    sma.push(slice.reduce((a, b) => a + b, 0) / slice.length)
  }
  const x = xScale.value
  const y = volScaleY.value
  let d = ''
  sma.forEach((v, i) => {
    d += `${i === 0 ? 'M' : 'L'}${x(i).toFixed(2)},${y(v).toFixed(2)}`
  })
  return d
})

/* Value area shading — 70% of traded volume. */
const vaRect = computed(() => {
  const va = vap.value
  if (!va || typeof va.value_area_low !== 'number' || typeof va.value_area_high !== 'number') {
    return null
  }
  const y = yScale.value
  const top = y(va.value_area_high)
  const bot = y(va.value_area_low)
  return { x: plotX0.value, y: top, w: plotX1.value - plotX0.value, h: Math.max(1, bot - top) }
})

/* Point of control */
const pocY = computed(() => {
  const poc = vap.value?.poc
  return typeof poc === 'number' ? yScale.value(poc) : null
})

interface LevelBand {
  key: string
  y1: number
  y2: number
  yMid: number
  tagY: number
  kind: string
  price: number
  tag: string
  reversed: boolean
  opacity: number
  support: boolean
}

/* Support / resistance bands */
const levelBands = computed<LevelBand[]>(() => {
  const y = yScale.value
  const raw = levels.value.map((l, idx) => {
    const topP = typeof l.high === 'number' ? l.high : l.price
    const botP = typeof l.low === 'number' ? l.low : l.price
    const y1 = y(topP)
    const y2 = y(botP)
    const yMid = y(l.price)
    const strength = clamp01(typeof l.strength === 'number' ? l.strength : 0.5)
    const support = /support/i.test(String(l.kind))
    const touches = typeof l.touches === 'number' ? `×${l.touches}` : ''
    return {
      key: levelKey(l, idx),
      y1,
      y2: Math.max(y2, y1 + 2),
      yMid,
      tagY: yMid - 4,
      kind: l.kind,
      price: l.price,
      tag: `${support ? 'S' : 'R'} ${l.price.toFixed(2)}${touches ? ` ${touches}` : ''}`,
      reversed: l.role_reversed === true,
      opacity: 0.04 + strength * 0.1,
      support,
    }
  })
  const ordered = [...raw].sort((a, b) => a.yMid - b.yMid)
  let lastTagY = -Infinity
  for (const band of ordered) {
    band.tagY = Math.max(band.yMid - 4, lastTagY + 12)
    lastTagY = band.tagY
  }
  return raw
})

/* Volume-at-price profile, anchored to the right edge */
interface ProfileRow {
  x: number
  y: number
  w: number
  h: number
  inVa: boolean
  poc: boolean
}
const profileRows = computed<ProfileRow[]>(() => {
  const va = vap.value
  if (!va?.bins?.length) return []
  const maxBin = va.bins.reduce((m, b) => Math.max(m, b.volume || 0), 0) || 1
  const y = yScale.value
  const right = plotX1.value
  return va.bins
    .filter((b) => Number.isFinite(b.low) && Number.isFinite(b.high))
    .map((b) => {
      const yTop = y(b.high)
      const yBot = y(b.low)
      const w = ((b.volume || 0) / maxBin) * profileW.value
      const inVa =
        typeof va.value_area_low === 'number' &&
        typeof va.value_area_high === 'number' &&
        b.low >= va.value_area_low &&
        b.high <= va.value_area_high
      const isPoc = typeof va.poc === 'number' && b.low <= va.poc && b.high >= va.poc
      return {
        x: right - w,
        y: yTop,
        w,
        h: Math.max(1, yBot - yTop - 0.5),
        inVa,
        poc: isPoc,
      }
    })
})

const tradeLines = computed(() => {
  const g = analysisResult.value?.trade_execution_guide
  if (!hasTradeLevels.value || !g) return []
  const y = yScale.value
  const lines = [
    {
      key: 'entry',
      y: y(g.entry_price!),
      label: `ENT ${g.entry_price!.toFixed(2)}`,
      cls: 'tl-entry',
      labelY: 0,
    },
    {
      key: 'stop',
      y: y(g.stop_price!),
      label: `STP ${g.stop_price!.toFixed(2)}`,
      cls: 'tl-stop',
      labelY: 0,
    },
    {
      key: 'target',
      y: y(g.target_price!),
      label: `TGT ${g.target_price!.toFixed(2)}`,
      cls: 'tl-target',
      labelY: 0,
    },
  ]
  const ordered = [...lines].sort((a, b) => a.y - b.y)
  let lastY = -Infinity
  for (const line of ordered) {
    line.labelY = Math.max(line.y, lastY + 13)
    lastY = line.labelY
  }
  return lines
})

const selectedEvidence = computed(() => {
  const i = selectedEvidenceIdx.value
  if (i === null) return null
  return orderedEvidence.value[i] ?? null
})

const evidenceMarks = computed(() => {
  const ev = selectedEvidence.value
  if (!ev?.bars?.length) return []
  const x = xScale.value
  const hw = candleHalfWidth.value + 1.4
  const start = visibleStart.value
  return ev.bars
    .map((barIdx) => {
      const vi = barIdx - start
      if (vi < 0 || vi >= visibleBars.value.length) return null
      return {
        x: x(vi) - hw,
        y: priceY0.value,
        w: hw * 2,
        h: priceY1.value - priceY0.value,
        idx: barIdx,
      }
    })
    .filter((m): m is NonNullable<typeof m> => m !== null)
})

const lastCloseY = computed(() => {
  const bars = visibleBars.value
  const last = bars[bars.length - 1]
  return last ? yScale.value(last.c) : null
})

const timeAxis = computed(() => {
  const bars = visibleBars.value
  if (!bars.length) return null
  return { first: fmtBarDate(bars[0].d), last: fmtBarDate(bars[bars.length - 1].d) }
})

const chartMeta = computed(() => {
  const n = chartBars.value.length
  const vis = visibleBars.value.length
  const live = liveBar.value ? ' · forming bar shown, not scored' : ''
  if (n === 0) return 'no bars'
  if (vis < n) return `last ${vis} of ${n} bars${live}`
  return `${n} bars${live}`
})

const lastPrice = computed<number | null>(() => {
  const bars = chartBars.value
  const last = bars[bars.length - 1]
  return last ? last.c : null
})

const srLadder = computed(() => {
  const last = lastPrice.value
  const rows = orderedLevels.value.map((l, idx) => {
    const dist = last !== null && last > 0 ? ((l.price - last) / last) * 100 : null
    return {
      key: levelKey(l, idx),
      level: l,
      label: levelKindLabel(l.kind),
      support: /support/i.test(l.kind),
      dist,
      distLabel: dist === null ? DASH : `${dist >= 0 ? '+' : ''}${dist.toFixed(2)}%`,
    }
  })
  return rows
})

const riskLadder = computed<VpaRiskLadder | null>(() => {
  if (!hasTradeLevels.value) return null
  const g = analysisResult.value!.trade_execution_guide
  return buildRiskLadder({
    entry: g.entry_price!,
    stop: g.stop_price!,
    target: g.target_price!,
    last: lastPrice.value,
  })
})

function selectEvidence(idx: number): void {
  selectedEvidenceIdx.value = selectedEvidenceIdx.value === idx ? null : idx
}

function evidenceBarRange(ev: VpaEvidenceItem): string {
  const dates = ev.bar_dates
  if (dates && dates.length) {
    if (dates.length === 1) return dates[0]
    return `${dates[0]} → ${dates[dates.length - 1]}`
  }
  const idxs = ev.bars
  if (!idxs?.length) return DASH
  const series = equityBars.value
  const first = series[idxs[0]]
  const last = series[idxs[idxs.length - 1]]
  if (!first && !last) return `bars ${idxs.join(', ')}`
  const a = fmtBarDate(first?.d)
  const b = fmtBarDate(last?.d)
  return a === b ? a : `${a} → ${b}`
}

function evidencePriceWindow(ev: VpaEvidenceItem): string {
  const idxs = ev.bars
  if (!idxs?.length) return DASH
  const series = equityBars.value
  let lo = Infinity
  let hi = -Infinity
  for (const i of idxs) {
    const b = series[i]
    if (!b) continue
    lo = Math.min(lo, b.l)
    hi = Math.max(hi, b.h)
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return DASH
  return `${fmtPrice(lo)} – ${fmtPrice(hi)}`
}

function renderCanvasChart(): void {
  /* SVG chart is reactive; kept so vision snapshot / tests still have a redraw hook. */
}

function onCanvasMouseMove(e: MouseEvent): void {
  const host = hostRef.value
  if (!host || visibleBars.value.length === 0) return
  const rect = host.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top
  const x = xScale.value
  const n = visibleBars.value.length
  const idx = Math.round(x.invert(mouseX))
  if (idx >= 0 && idx < n && mouseX >= plotX0.value && mouseX <= candleX1.value) {
    hoveredBar.value = { bar: visibleBars.value[idx], x: mouseX, y: mouseY, idx }
  } else {
    hoveredBar.value = null
  }
  const band = levelBands.value.find(
    (b) => mouseY >= Math.min(b.y1, b.y2) - 3 && mouseY <= Math.max(b.y1, b.y2) + 3,
  )
  const nextKey = band ? band.key : null
  if (nextKey !== hoveredLevelKey.value) hoveredLevelKey.value = nextKey
}

function onCanvasMouseLeave(): void {
  hoveredBar.value = null
  hoveredLevelKey.value = null
}

/* --------------------------------------------------------------- classes */

const verdictColorClass = computed(() => {
  const v = analysisResult.value?.effort_vs_result_verdict
  if (v === 'VALIDATION') return 'pos'
  if (v === 'ANOMALY') return 'warn'
  return 'flat'
})

const directionColorClass = computed(() => {
  const d = analysisResult.value?.primary_scenario?.direction
  if (d === 'BULLISH') return 'pos'
  if (d === 'BEARISH') return 'neg'
  return 'warn'
})

function evidenceDirClass(dir: string): string {
  if (/bull/i.test(dir)) return 'pos'
  if (/bear|fake/i.test(dir)) return 'neg'
  return 'flat'
}

function evidenceBarWidth(w?: number): string {
  const max = maxEvidenceWeight.value
  if (!max || typeof w !== 'number') return '0%'
  return `${Math.min(100, (Math.abs(w) / max) * 100).toFixed(1)}%`
}

/* -------------------------------------------------------------- watchers */

let paramReloadTimer: ReturnType<typeof setTimeout> | null = null
let suppressParamWatch = false

/**
 * Changing the timeframe, lookback or asset class re-runs the analysis. Without
 * this the selector was pure decoration: the payload label changed, nothing refetched.
 */
watch([timeframeInput, assetClassInput], ([tf, ac], [prevTf, prevAc]) => {
  if (suppressParamWatch) return
  if (tf === prevTf && ac === prevAc) return
  if (ingestionMode.value !== 'symbol' || !symbolInput.value) return
  if (paramReloadTimer) clearTimeout(paramReloadTimer)
  paramReloadTimer = setTimeout(() => {
    paramReloadTimer = null
    fetchEquityDataAndAnalyze(symbolInput.value)
  }, 120)
})

watch(lookbackBars, () => {
  if (suppressParamWatch) return
  if (ingestionMode.value !== 'symbol' || !symbolInput.value) return
  if (paramReloadTimer) clearTimeout(paramReloadTimer)
  paramReloadTimer = setTimeout(() => {
    paramReloadTimer = null
    fetchEquityDataAndAnalyze(symbolInput.value)
  }, 120)
})

watch(hoveredLevelKey, () => {
  renderCanvasChart()
})
</script>

<template>
  <div class="vpa-view-root">
    <!-- Top Header -->
    <header class="vpa-top-bar">
      <div class="header-left">
        <div class="icon-frame">
          <AppIcon name="vpa" :size="20" />
        </div>
        <div class="title-block">
          <div class="title-row">
            <h1 class="view-title">Volume Price Analysis</h1>
            <span class="version-pill">Volume-price rules</span>
            <span v-if="analysisResult?.engine_mode" class="engine-pill fig">
              {{ analysisResult.engine_mode }}
            </span>
          </div>
          <p class="view-subtitle">
            Effort vs. result, volume at price, Wyckoff campaign phase and explicit invalidation —
            every figure traced to the bars it came from.
          </p>
        </div>
      </div>

      <div class="header-right">
        <!-- Ingestion Mode Selector -->
        <div class="mode-toggle-group">
          <button
            class="mode-btn"
            :class="{ active: ingestionMode === 'symbol' }"
            @click="ingestionMode = 'symbol'"
          >
            <AppIcon name="brief" :size="14" />
            <span>Equity Chart</span>
          </button>
          <button
            class="mode-btn"
            :class="{ active: ingestionMode === 'screenshot' }"
            @click="ingestionMode = 'screenshot'"
          >
            <AppIcon name="vpa" :size="14" />
            <span>Screenshot / Paste</span>
          </button>
        </div>

        <button
          class="action-btn codex-btn"
          title="Open volume-price rules"
          @click="codexDrawerOpen = !codexDrawerOpen"
        >
          <AppIcon name="brief" :size="16" />
          <span>VPA Codex &amp; Rules</span>
        </button>
        <button
          v-if="currentImage || analysisResult || equityBars.length > 0"
          class="action-btn clear-btn"
          @click="clearChart"
        >
          <span>Clear</span>
        </button>
      </div>
    </header>

    <!-- Alert Banners -->
    <div v-if="errorMsg" class="alert-banner neg-banner">
      <span class="banner-tag">Error</span>
      <span>{{ errorMsg }}</span>
    </div>
    <div v-if="downgraded" class="alert-banner warn-banner">
      <span class="banner-tag">Timeframe downgraded</span>
      <span>
        Requested <b class="fig">{{ fmtText(barsMeta?.timeframe_requested) }}</b
        >: served <b class="fig">{{ fmtText(barsMeta?.timeframe_served) }}</b
        >. {{ barsMeta?.downgrade_reason || 'No reason reported by the engine.' }}
      </span>
    </div>
    <div v-if="visionDroppedImage" class="alert-banner warn-banner">
      <span class="banner-tag">Snapshot discarded</span>
      <span>
        The engine received the chart image but did not use it{{
          visionReason ? ` — ${visionReason}` : ''
        }}. This read is from bars alone.
      </span>
    </div>
    <div v-if="analysisResult?.notice" class="alert-banner notice-banner">
      <span class="banner-tag">Notice</span>
      <span>{{ analysisResult.notice }}</span>
    </div>
    <div v-if="analysisResult?.warning" class="alert-banner warn-banner">
      <span class="banner-tag">Warning</span>
      <span>{{ analysisResult.warning }}</span>
    </div>

    <!-- Desk controls: timeframe + lookback as bar counts, same pattern as Liquidity / AMT -->
    <div v-if="ingestionMode === 'symbol'" class="desk-controls">
      <input
        v-model="symbolInput"
        type="text"
        maxlength="10"
        autocomplete="off"
        spellcheck="false"
        placeholder="SYMBOL"
        class="symbol-main-input fig"
        aria-label="Symbol"
        @keydown.enter="fetchEquityDataAndAnalyze(symbolInput)"
      />
      <button
        class="fetch-btn"
        :disabled="fetchingTrajectory || analyzing"
        @click="fetchEquityDataAndAnalyze(symbolInput)"
      >
        <span v-if="fetchingTrajectory" class="spinner"></span>
        <span v-else>Load</span>
      </button>
      <div class="seg" role="group" aria-label="Timeframe">
        <button
          v-for="tf in timeframeOptions.filter((t) => t.available)"
          :key="tf.value"
          type="button"
          class="seg-btn fig"
          :class="{ on: timeframeInput === tf.value }"
          :aria-pressed="timeframeInput === tf.value"
          :disabled="!capabilityKnown"
          :title="tf.reason || undefined"
          @click="timeframeInput = tf.value"
        >
          {{ tf.label }}
        </button>
        <span v-if="!capabilityKnown" class="seg-fallback fig"
          >{{ timeframeInput }} (unverified)</span
        >
      </div>
      <select
        id="vpa-timeframe"
        v-model="timeframeInput"
        class="field-select fig tf-native"
        :disabled="!capabilityKnown"
        aria-label="Timeframe"
      >
        <option v-if="!capabilityKnown" :value="timeframeInput">
          {{ timeframeInput }} (unverified)
        </option>
        <option
          v-for="tf in timeframeOptions"
          :key="'opt-' + tf.value"
          :value="tf.value"
          :disabled="!tf.available"
          :title="tf.available ? undefined : tf.reason || 'no data for this timeframe'"
        >
          {{ tf.label }}{{ tf.available ? '' : ` — unavailable (${tf.reason || 'no data'})` }}
        </option>
      </select>
      <select
        id="vpa-asset"
        v-model="assetClassInput"
        class="field-select"
        aria-label="Asset class"
      >
        <option v-for="ac in assetClasses" :key="ac.value" :value="ac.value">
          {{ ac.label }}
        </option>
      </select>
      <div class="seg" role="group" aria-label="Lookback bars">
        <button
          v-for="w in LOOKBACKS"
          :key="w.value"
          type="button"
          class="seg-btn fig"
          :class="{ on: lookbackBars === w.value }"
          :aria-pressed="lookbackBars === w.value"
          @click="lookbackBars = w.value"
        >
          {{ w.label }}
        </button>
      </div>
      <span class="lookback-unit label">bars</span>
      <div class="quick-chips-row">
        <button
          v-for="sym in popularEquities"
          :key="sym"
          class="chip-btn fig"
          :class="{ active: symbolInput.toUpperCase() === sym }"
          @click="fetchEquityDataAndAnalyze(sym)"
        >
          {{ sym }}
        </button>
      </div>
    </div>
    <p v-if="!capabilityKnown" class="cap-note is-warn">
      Timeframe capability report unavailable{{ healthError ? ` (${healthError})` : '' }}. The
      selector is locked rather than offer timeframes this server may not be able to serve.
    </p>
    <p v-else-if="timeframeNote" class="cap-note is-warn">{{ timeframeNote }}</p>
    <p v-else-if="unavailableTimeframes.length" class="cap-note">
      Unavailable on this deployment:
      <span v-for="(tf, i) in unavailableTimeframes" :key="tf.value" class="cap-off">
        {{ tf.label }}<span class="cap-reason"> ({{ tf.reason || 'no data' }})</span
        >{{ i < unavailableTimeframes.length - 1 ? ', ' : '' }} </span
      >.
    </p>

    <!-- MODE 1: Equity candlestick -->
    <div v-if="ingestionMode === 'symbol'" class="vpa-card chart-card">
      <div class="card-header">
        <span class="label">Price · volume · structure</span>
        <span class="chart-meta fig">{{ chartMeta }}</span>
      </div>
      <div
        ref="hostRef"
        class="chart-host"
        @mousemove="onCanvasMouseMove"
        @mouseleave="onCanvasMouseLeave"
      >
        <svg
          v-if="visibleBars.length"
          ref="chartSvg"
          class="vpa-svg"
          :width="W"
          :height="H"
          :viewBox="`0 0 ${W} ${H}`"
          preserveAspectRatio="none"
          role="img"
          aria-label="Candlesticks with volume, support and resistance bands, value area, point of control and trade levels."
        >
          <g v-for="t in priceTicks" :key="`pt-${t}`">
            <line :x1="plotX0" :x2="plotX1" :y1="yScale(t)" :y2="yScale(t)" class="grid-line" />
            <text :x="plotX1 + 6" :y="yScale(t) + 3" class="axis-label fig">
              ${{ t.toFixed(2) }}
            </text>
          </g>

          <rect
            v-if="vaRect"
            :x="vaRect.x"
            :y="vaRect.y"
            :width="vaRect.w"
            :height="vaRect.h"
            class="va-fill"
          />

          <g
            v-for="b in levelBands"
            :key="`lv-${b.key}`"
            :class="[
              'lvl-band',
              b.support ? 'is-sup' : 'is-res',
              { hot: hoveredLevelKey === b.key, reversed: b.reversed },
            ]"
          >
            <rect
              :x="plotX0"
              :y="Math.min(b.y1, b.y2)"
              :width="plotX1 - plotX0"
              :height="Math.abs(b.y2 - b.y1)"
              class="lvl-zone"
              :fill-opacity="b.opacity + (hoveredLevelKey === b.key ? 0.18 : 0)"
            />
            <line
              :x1="plotX0"
              :x2="plotX1"
              :y1="b.yMid"
              :y2="b.yMid"
              class="lvl-edge"
              :class="{ dashed: b.reversed }"
            />
            <text :x="plotX0 + 6" :y="b.tagY" class="lvl-tag fig">{{ b.tag }}</text>
          </g>

          <rect
            v-for="(row, i) in profileRows"
            :key="`vap-${i}`"
            :x="row.x"
            :y="row.y"
            :width="row.w"
            :height="row.h"
            :class="['vap-bar', { in: row.inVa, poc: row.poc }]"
          />

          <rect
            v-for="m in evidenceMarks"
            :key="`ev-${m.idx}`"
            :x="m.x"
            :y="m.y"
            :width="m.w"
            :height="m.h"
            class="ev-mark"
          />

          <path :d="candleGeom.wicks" class="candle-wick" />
          <path :d="candleGeom.up" class="candle-up" />
          <path :d="candleGeom.down" class="candle-down" />

          <g v-for="tl in tradeLines" :key="`tl-${tl.key}`">
            <line
              :x1="plotX0"
              :x2="candleX1"
              :y1="tl.y"
              :y2="tl.y"
              :class="['trade-line', tl.cls]"
            />
            <text
              :x="candleX1 - 4"
              :y="tl.labelY - 3"
              text-anchor="end"
              :class="['trade-label fig', tl.cls]"
            >
              {{ tl.label }}
            </text>
          </g>

          <g v-if="pocY != null">
            <line :x1="plotX0" :x2="plotX1" :y1="pocY" :y2="pocY" class="poc-line" />
            <text :x="plotX1 - 4" :y="pocY - 4" text-anchor="end" class="poc-label fig">
              POC {{ fmtPrice(vap?.poc) }}
            </text>
          </g>

          <g v-if="lastCloseY != null">
            <line :x1="plotX0" :x2="plotX1" :y1="lastCloseY" :y2="lastCloseY" class="last-line" />
          </g>

          <rect
            v-for="(v, i) in volRects"
            :key="`vol-${i}`"
            :x="v.x"
            :y="v.y"
            :width="v.w"
            :height="v.h"
            :class="['vol-bar', v.up ? 'up' : 'down', { live: v.live }]"
          />
          <path :d="volSmaPath" class="vol-sma" />

          <g v-if="timeAxis">
            <text :x="plotX0 + 4" :y="H - 8" class="axis-label">{{ timeAxis.first }}</text>
            <text :x="candleX1 - 4" :y="H - 8" text-anchor="end" class="axis-label">
              {{ timeAxis.last }}
            </text>
          </g>
        </svg>
        <p v-else class="chart-state">
          {{ fetchingTrajectory ? 'Loading bars…' : 'No chart data loaded' }}
        </p>
        <div
          v-if="hoveredBar"
          class="canvas-tooltip"
          :style="{ left: `${hoveredBar.x + 12}px`, top: `${Math.min(hoveredBar.y, 170)}px` }"
        >
          <div class="tt-date">
            {{ fmtBarDate(hoveredBar.bar.d)
            }}<span v-if="hoveredBar.bar.live" class="tt-live"> forming</span>
          </div>
          <div class="tt-row fig">
            <span>O</span><b>{{ fmtPrice(hoveredBar.bar.o) }}</b> <span>H</span
            ><b>{{ fmtPrice(hoveredBar.bar.h) }}</b>
          </div>
          <div class="tt-row fig">
            <span>L</span><b>{{ fmtPrice(hoveredBar.bar.l) }}</b> <span>C</span
            ><b>{{ fmtPrice(hoveredBar.bar.c) }}</b>
          </div>
          <div class="tt-vol fig">Vol {{ fmtInt(hoveredBar.bar.v) }}</div>
        </div>
      </div>
      <div class="chart-legend">
        <span class="lg-item"><i class="sw sw-sup"></i>Support zone</span>
        <span class="lg-item"><i class="sw sw-res"></i>Resistance zone</span>
        <span class="lg-item"><i class="sw sw-poc"></i>POC</span>
        <span class="lg-item"><i class="sw sw-va"></i>Value area</span>
        <span class="lg-item"><i class="sw sw-rr"></i>Role reversed</span>
        <span class="lg-item"><i class="sw sw-ent"></i>Entry / stop / target</span>
        <span v-if="levels.length === 0 && !hasVap" class="lg-empty">
          No structure in this response: nothing overlaid.
        </span>
      </div>
      <div class="under-canvas">
        <span class="uc-meta fig">
          {{ equityBars.length }} scored bars · 20-bar volume MA · {{ levels.length }} levels
        </span>
        <button
          class="snap-btn"
          :class="{ 'is-blocked': snapDisabled }"
          :disabled="snapDisabled"
          :title="snapBlockedReason || 'Send the rendered chart for multimodal reading'"
          @click="snapCanvasToVision"
        >
          <AppIcon :name="snapDisabled ? 'eye-off' : 'cloud'" :size="13" />
          <span>{{ snapDisabled ? 'Vision Not Configured' : 'Snapshot to Vision AI' }}</span>
        </button>
      </div>
      <p v-if="snapBlockedReason" class="snap-reason">{{ snapBlockedReason }}</p>

      <div class="bars-meta-panel">
        <div class="bmp-head">
          <AppIcon name="database" :size="13" />
          <span class="label">Bars Served To The Engine</span>
          <span v-if="downgraded" class="status-chip chip-warn">Downgraded</span>
          <button
            class="mini-btn"
            :disabled="healthLoading"
            title="Re-probe GET /api/vpa/health"
            @click="loadHealth"
          >
            {{ healthLoading ? 'Probing…' : 'Recheck capability' }}
          </button>
        </div>
        <template v-if="barsMeta">
          <dl class="bmp-grid">
            <div class="bmp-cell">
              <dt class="label">Requested</dt>
              <dd class="fig">{{ fmtText(barsMeta.timeframe_requested) }}</dd>
            </div>
            <div class="bmp-cell">
              <dt class="label">Served</dt>
              <dd class="fig" :class="{ warn: downgraded }">
                {{ fmtText(barsMeta.timeframe_served) }}
              </dd>
            </div>
            <div class="bmp-cell">
              <dt class="label">Bar count</dt>
              <dd class="fig">{{ fmtInt(barsMeta.bar_count) }}</dd>
            </div>
            <div class="bmp-cell">
              <dt class="label">Lookback</dt>
              <dd class="fig">{{ fmtInt(barsMeta.lookback_requested ?? lookbackBars) }}</dd>
            </div>
            <div v-if="barsMeta.resampled_from" class="bmp-cell">
              <dt class="label">Resampled from</dt>
              <dd class="fig warn">{{ barsMeta.resampled_from }}</dd>
            </div>
            <div class="bmp-cell">
              <dt class="label">First bar</dt>
              <dd class="fig">{{ fmtStamp(barsMeta.first_bar) }}</dd>
            </div>
            <div class="bmp-cell">
              <dt class="label">Last bar</dt>
              <dd class="fig">{{ fmtStamp(barsMeta.last_bar) }}</dd>
            </div>
            <div v-if="barsMeta.live_bar" class="bmp-cell">
              <dt class="label">Forming</dt>
              <dd class="fig warn">{{ fmtBarDate(barsMeta.live_bar.d) }} (not scored)</dd>
            </div>
            <div class="bmp-cell bmp-wide">
              <dt class="label">Source</dt>
              <dd class="fig src">{{ fmtText(barsMeta.source) }}</dd>
            </div>
          </dl>
          <p v-if="chartServedMismatch" class="bmp-note">
            The canvas above paints daily bars from <code>/api/trajectory</code>; the engine read
            <b class="fig">{{ barsMeta.timeframe_served }}</b> bars. Treat the drawing as context,
            the figures as the analysis.
          </p>
        </template>
        <p v-else class="bmp-empty">
          This response carried no <code>bars_meta</code>, so there is no proof of which bars were
          analysed.
          <template v-if="!serverLoadsBars">
            Legacy path: the browser is supplying daily bars from
            <code>/api/trajectory</code>, so the timeframe selector cannot take effect yet.
          </template>
        </p>
      </div>
      <div class="run-row">
        <p v-if="lastScanAt" class="scan-receipt" aria-live="polite">
          <span class="fig">Scanned {{ scanStamp }}</span>
          <span v-if="lastScanChanged === false" class="scan-same"
            >· read unchanged — same bars, deterministic engine</span
          >
          <span v-else-if="lastScanChanged === true" class="scan-moved">· read updated</span>
        </p>
        <button
          class="run-btn"
          :disabled="analyzing || (!currentImage && equityBars.length === 0 && !analysisResult)"
          @click="runAnalysis()"
        >
          <span v-if="analyzing" class="spinner"></span>
          <span v-else>Run VPA Forensic Scan</span>
        </button>
      </div>
    </div>

    <!-- MODE 2: Paste / Dropzone Area -->
    <div
      v-if="ingestionMode === 'screenshot'"
      class="upload-card"
      :class="{ 'is-dragging': isDragging, 'has-image': !!currentImage }"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <template v-if="!currentImage && !analysisResult">
        <div class="dropzone-content">
          <div class="paste-icon-box">
            <AppIcon name="vpa" :size="36" />
          </div>
          <h3 class="dz-title">Paste Chart Screenshot (⌘V / Ctrl+V)</h3>
          <p class="dz-body">
            Copy any candlestick chart from TradingView, MT4, NinjaTrader or ThinkOrSwim and press
            ⌘V / Ctrl+V anywhere on this screen.
          </p>
          <p v-if="visionAvailable === false" class="dz-warn">
            Chart vision is not configured, so a pasted image will not be read directly. For any
            symbol held locally you do not need it: type the ticker on the left and the engine reads
            the exact OHLCV bars, which is more precise than inferring candles from pixels.
          </p>
          <div class="dz-actions">
            <label class="file-upload-label">
              <input type="file" accept="image/*" class="hidden-input" @change="onFileSelected" />
              <span>Choose File</span>
            </label>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="chart-preview-container">
          <div class="preview-header">
            <div class="ph-left fig">
              <span class="ph-sym">{{ symbolInput || analysisResult?.symbol || 'CHART' }}</span>
              <span class="ph-sep">·</span>
              <span class="ph-tf">{{ analysisResult?.timeframe || timeframeLabel || DASH }}</span>
            </div>
            <label class="change-file-btn">
              <input type="file" accept="image/*" class="hidden-input" @change="onFileSelected" />
              <span>Upload New</span>
            </label>
          </div>
          <div class="preview-body">
            <img v-if="currentImage" :src="currentImage" alt="Chart Screenshot" class="chart-img" />
            <div v-else class="sample-badge-banner">
              <span class="sbb-title">{{
                analysisResult?.sample_title || 'Canonical Reference Chart'
              }}</span>
              <span class="sbb-ref">{{ analysisResult?.book_reference }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- Workspace Grid -->
    <div class="vpa-grid">
      <!-- Right Column: Forensic Results & Scenarios -->
      <div class="vpa-col-right">
        <!-- Results Card -->
        <div v-if="analysisResult" class="vpa-card" :class="{ 'is-reference': isReferenceCase }">
          <!-- Provenance banner for canned book cases (defect D8) -->
          <div v-if="isReferenceCase" class="provenance-strip">
            <div class="prov-mark">
              <AppIcon name="brief" :size="16" />
            </div>
            <div class="prov-text">
              <div class="prov-title">Stored reference — not a live read</div>
              <div class="prov-sub">
                {{ analysisResult.sample_title || 'Reference case' }}
                <span v-if="analysisResult.book_reference" class="prov-cite">{{
                  analysisResult.book_reference
                }}</span>
              </div>
              <p v-if="analysisResult.description" class="prov-desc">
                {{ analysisResult.description }}
              </p>
            </div>
          </div>

          <!-- Summary Hero Banner -->
          <div class="hero-summary-strip">
            <div class="metric-col">
              <div class="metric-label label">Market Phase</div>
              <div class="metric-val phos">{{ fmtText(analysisResult.market_phase) }}</div>
            </div>
            <div class="metric-col">
              <div class="metric-label label">Effort vs. Result</div>
              <div class="metric-val fig" :class="verdictColorClass">
                {{ fmtText(analysisResult.effort_vs_result_verdict) }}
              </div>
            </div>
            <div class="metric-col">
              <div class="metric-label label">Dominant Sentiment</div>
              <div class="metric-val">{{ fmtText(analysisResult.dominant_sentiment) }}</div>
            </div>
            <div class="metric-col">
              <div class="metric-label label">Confidence</div>
              <div class="metric-val fig" :class="confidencePct === null ? 'flat' : 'pos'">
                {{ confidencePct === null ? DASH : `${confidencePct}%` }}
              </div>
            </div>
          </div>

          <!-- VPA Clean Read / Tactical Briefing Card -->
          <div v-if="vpaRead" class="vpa-clean-read-card">
            <div class="cr-top">
              <div class="cr-badge" :class="`cr-tone-${vpaRead.stanceTone}`">
                <span class="cr-stance">{{ vpaRead.stanceLabel }}</span>
                <span class="cr-headline">{{ vpaRead.summaryHeadline }}</span>
              </div>
              <div class="cr-meta fig">
                <span class="cr-meta-item" :class="vpaRead.confidenceTone">
                  {{ vpaRead.confidencePct !== null ? `${vpaRead.confidencePct}%` : DASH }}
                  confidence
                </span>
                <span class="cr-sep">·</span>
                <span class="cr-meta-item" :class="vpaRead.plan.riskRewardTone">
                  R:R {{ vpaRead.plan.riskReward }}
                </span>
              </div>
            </div>

            <p class="cr-executive-prose">{{ vpaRead.executiveReadout }}</p>

            <div
              v-if="riskLadder"
              class="risk-ladder"
              role="img"
              :aria-label="`Price staff, high at top. ${riskLadder.rungs.map((r) => `${r.label} ${fmtPrice(r.price)}`).join('. ')}`"
            >
              <div class="rl-head">
                <span class="label">Price staff</span>
                <span class="rl-span fig"
                  >{{ fmtPrice(riskLadder.hi) }} → {{ fmtPrice(riskLadder.lo) }}</span
                >
              </div>
              <ol class="rl-rungs">
                <li
                  v-for="rung in riskLadder.rungs"
                  :key="rung.label + rung.price"
                  class="rl-rung"
                  :class="[`tone-${rung.tone}`, { 'is-entry': rung.isEntry }]"
                >
                  <span class="rl-roles">{{ rung.label }}</span>
                  <span class="rl-tick" aria-hidden="true">
                    <i v-if="rung.segBelow" class="rl-seg" :class="`seg-${rung.segBelow}`" />
                  </span>
                  <b class="rl-px fig">{{ fmtPrice(rung.price) }}</b>
                  <span class="rl-delta fig">{{ rung.deltaLabel }}</span>
                </li>
              </ol>
              <div class="rl-foot fig">
                <span class="rl-risk">Risk {{ fmtNum(riskLadder.risk) }}</span>
                <span class="cr-sep">·</span>
                <span class="rl-reward">Reward {{ fmtNum(riskLadder.reward) }}</span>
              </div>
            </div>

            <div class="cr-blueprint-grid">
              <div class="cr-cell">
                <span class="label wraps">Entry trigger</span>
                <span class="cr-cell-val">{{ vpaRead.plan.trigger }}</span>
              </div>
              <div class="cr-cell">
                <span class="label wraps">Stop placement</span>
                <span class="cr-cell-val fig" :class="vpaRead.plan.stopPlacementTone">{{
                  vpaRead.plan.stopPlacement
                }}</span>
              </div>
              <div class="cr-cell">
                <span class="label wraps">Target zone</span>
                <span class="cr-cell-val fig" :class="vpaRead.plan.targetZoneTone">{{
                  vpaRead.plan.targetZone
                }}</span>
              </div>
              <div class="cr-cell">
                <span class="label wraps">Invalidation</span>
                <span class="cr-cell-val fig" :class="vpaRead.plan.invalidationTone">{{
                  vpaRead.plan.invalidation
                }}</span>
              </div>
            </div>

            <div class="cr-levels-strip">
              <div class="cr-lvl-item">
                <span class="label">POC</span>
                <b class="fig" :class="{ warn: vpaRead.structure.poc !== null }">{{
                  fmtPrice(vpaRead.structure.poc)
                }}</b>
              </div>
              <div class="cr-lvl-item">
                <span class="label">Value area</span>
                <b class="fig"
                  >{{ fmtPrice(vpaRead.structure.val) }} – {{ fmtPrice(vpaRead.structure.vah) }}</b
                >
              </div>
              <div class="cr-lvl-item">
                <span class="label">Nearest support</span>
                <b class="fig" :class="{ pos: vpaRead.structure.nearestSupport !== null }">{{
                  fmtPrice(vpaRead.structure.nearestSupport?.price)
                }}</b>
              </div>
              <div class="cr-lvl-item">
                <span class="label">Nearest resistance</span>
                <b class="fig" :class="{ neg: vpaRead.structure.nearestResistance !== null }">{{
                  fmtPrice(vpaRead.structure.nearestResistance?.price)
                }}</b>
              </div>
              <div v-if="vpaRead.topSignals.length" class="cr-lvl-item cr-signals-item">
                <span class="label">Active signals</span>
                <span class="cr-sig-tags">
                  <button
                    v-for="(sig, sIdx) in vpaRead.topSignals.slice(0, 3)"
                    :key="sIdx"
                    type="button"
                    class="cr-sig-chip"
                    :class="
                      sig.direction === 'bullish'
                        ? 'pos'
                        : sig.direction === 'bearish'
                          ? 'neg'
                          : 'flat'
                    "
                    @click="
                      selectedTab = 'scenarios';
                      selectEvidence(sIdx);
                    "
                  >
                    {{ sig.name }}
                  </button>
                </span>
              </div>
            </div>
          </div>

          <!-- Section Tabs -->
          <div class="vpa-tabs" role="tablist">
            <button
              class="tab-btn"
              role="tab"
              :aria-selected="selectedTab === 'analysis'"
              :class="{ active: selectedTab === 'analysis' }"
              @click="selectedTab = 'analysis'"
            >
              Forensic Candles &amp; Laws
            </button>
            <button
              class="tab-btn"
              role="tab"
              :aria-selected="selectedTab === 'scenarios'"
              :class="{ active: selectedTab === 'scenarios' }"
              @click="selectedTab = 'scenarios'"
            >
              Scenarios &amp; Invalidation
            </button>
            <button
              class="tab-btn"
              role="tab"
              :aria-selected="selectedTab === 'execution'"
              :class="{ active: selectedTab === 'execution' }"
              @click="selectedTab = 'execution'"
            >
              Trade Framing &amp; Risk
            </button>
          </div>

          <!-- Tab Content 1: Forensic Analysis -->
          <div v-if="selectedTab === 'analysis'" class="tab-pane">
            <!-- Wyckoff Campaign Phase -->
            <section class="forensic-section">
              <h4 class="section-title">
                <AppIcon name="radar" :size="15" />
                <span>Wyckoff Campaign Context</span>
              </h4>
              <p class="prose-panel">
                {{ fmtText(analysisResult.forensic_breakdown.wyckoff_phase) }}
              </p>
            </section>

            <!-- Key Candles Table -->
            <section class="forensic-section">
              <h4 class="section-title">
                <AppIcon name="vpa" :size="15" />
                <span>Candle-by-Candle Forensic Evaluation</span>
              </h4>
              <div class="table-frame">
                <table class="vpa-table">
                  <thead>
                    <tr>
                      <th>Candle Signature</th>
                      <th class="num">Spread</th>
                      <th class="num">Volume</th>
                      <th>Effort / Result</th>
                      <th>Read</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(c, idx) in analysisResult.forensic_breakdown.key_candles"
                      :key="idx"
                    >
                      <td class="td-name">{{ c.candle_type }}</td>
                      <td class="num fig td-dim">{{ c.spread }}</td>
                      <td class="num fig td-dim">{{ c.volume }}</td>
                      <td>
                        <span
                          class="status-chip"
                          :class="c.verdict.includes('VALID') ? 'chip-pos' : 'chip-warn'"
                        >
                          {{ c.verdict }}
                        </span>
                      </td>
                      <td class="td-prose">{{ c.interpretation }}</td>
                    </tr>
                    <tr v-if="!analysisResult.forensic_breakdown.key_candles?.length">
                      <td colspan="5" class="td-empty">No candle detections in this response.</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- Stopping/Topping Volume & Tests Grid -->
            <div class="grid-2-col">
              <div class="sub-panel">
                <div class="sub-panel-header">
                  <span class="label">Stopping / Topping Dynamics</span>
                  <span
                    v-if="analysisResult.forensic_breakdown.stopping_or_topping.detected"
                    class="status-chip chip-pos"
                    >Active</span
                  >
                  <span v-else class="status-chip chip-neutral">None</span>
                </div>
                <div class="sp-body">
                  <div class="sp-headline">
                    {{ fmtText(analysisResult.forensic_breakdown.stopping_or_topping.type) }}
                  </div>
                  <p class="sp-detail">
                    {{ fmtText(analysisResult.forensic_breakdown.stopping_or_topping.details) }}
                  </p>
                </div>
              </div>

              <div class="sub-panel">
                <div class="sub-panel-header">
                  <span class="label">Low-Volume Tests (Supply / Demand)</span>
                  <span
                    v-if="analysisResult.forensic_breakdown.test_candles.detected"
                    class="status-chip chip-pos"
                    >Detected</span
                  >
                  <span v-else class="status-chip chip-neutral">None</span>
                </div>
                <div class="sp-body">
                  <div class="sp-headline">
                    {{ fmtText(analysisResult.forensic_breakdown.test_candles.type) }}
                  </div>
                  <p class="sp-detail">
                    {{ fmtText(analysisResult.forensic_breakdown.test_candles.result) }}
                  </p>
                </div>
              </div>
            </div>

            <!-- Dynamic trend line (Ch.8) & congestion geometry (Ch.11) -->
            <section class="forensic-section">
              <h4 class="section-title">
                <AppIcon name="momentum" :size="15" />
                <span>Dynamic Trend &amp; Congestion Geometry</span>
                <span class="title-sub">pivot structure, not a moving average</span>
              </h4>

              <div class="grid-2-col">
                <div class="sub-panel">
                  <div class="sub-panel-header">
                    <span class="label">Dynamic trend line</span>
                    <span
                      v-if="hasDynamicTrend"
                      class="status-chip"
                      :class="
                        dynamicTrend!.direction === 'none'
                          ? 'chip-neutral'
                          : evidenceDirClass(dynamicTrend!.direction) === 'pos'
                            ? 'chip-pos'
                            : 'chip-warn'
                      "
                      >{{ dynamicTrend!.direction }}</span
                    >
                    <span v-else class="status-chip chip-neutral">Not fitted</span>
                  </div>
                  <div v-if="hasDynamicTrend" class="sp-body">
                    <div class="struct-figs">
                      <div class="struct-fig">
                        <span class="label">Pivots</span>
                        <span class="fig struct-val">{{ fmtInt(dynamicTrend!.pivot_count) }}</span>
                      </div>
                      <div class="struct-fig">
                        <span class="label">ATR / bar</span>
                        <span class="fig struct-val">{{
                          fmtNum(dynamicTrend!.slope_atr_per_bar, 3)
                        }}</span>
                      </div>
                      <div class="struct-fig">
                        <span class="label">Price / bar</span>
                        <span class="fig struct-val">{{
                          fmtNum(dynamicTrend!.slope_per_bar, 3)
                        }}</span>
                      </div>
                    </div>
                    <p class="sp-detail">{{ fmtText(dynamicTrend!.detail) }}</p>
                    <div v-if="dynamicTrend!.pivot_bars?.length" class="ev-bars fig">
                      pivot bars {{ dynamicTrend!.pivot_bars!.join(', ') }}
                    </div>
                    <div v-if="dynamicTrend!.book_ref" class="struct-cite">
                      {{ dynamicTrend!.book_ref }}
                    </div>
                  </div>
                  <p v-else class="empty-note">
                    The engine returned no <code>dynamic_trend</code> for this window (fewer than 20
                    bars, or no pivot pair to fit a line through).
                  </p>
                </div>

                <div class="sub-panel">
                  <div class="sub-panel-header">
                    <span class="label">Congestion patterns</span>
                    <span v-if="congestionPatterns.length" class="status-chip chip-pos"
                      >{{ congestionPatterns.length }} found</span
                    >
                    <span v-else class="status-chip chip-neutral">None</span>
                  </div>
                  <div v-if="congestionPatterns.length" class="sp-body congestion-list">
                    <article
                      v-for="(p, idx) in congestionPatterns"
                      :key="`${p.pattern}-${idx}`"
                      class="congestion-row"
                      :class="evidenceDirClass(p.direction)"
                    >
                      <div class="cg-head">
                        <span class="sp-headline">{{ p.pattern }}</span>
                        <span class="cg-dir label">{{ p.direction }}</span>
                        <span v-if="typeof p.level === 'number'" class="fig cg-level">{{
                          fmtPrice(p.level)
                        }}</span>
                      </div>
                      <p class="sp-detail">{{ p.detail }}</p>
                      <div v-if="p.bars?.length" class="ev-bars fig">
                        bars {{ p.bars.join(', ') }}
                      </div>
                      <div v-if="p.book_ref" class="struct-cite">{{ p.book_ref }}</div>
                    </article>
                  </div>
                  <p v-else class="empty-note">
                    No pennant, flag or triangle resolved out of the pivots in this window.
                  </p>
                </div>
              </div>
            </section>

            <!-- Support, Resistance & VAP -->
            <section class="forensic-section levels-section">
              <h4 class="section-title">
                <AppIcon name="drift" :size="15" />
                <span>Support &amp; Resistance (The 'House' Model) &amp; VAP</span>
                <span v-if="levels.length" class="title-count fig">{{ levels.length }} zones</span>
              </h4>

              <ol v-if="srLadder.length && lastPrice !== null" class="sr-ladder">
                <li class="sr-spot">
                  <span class="label">Last</span>
                  <b class="fig">{{ fmtPrice(lastPrice) }}</b>
                </li>
                <li
                  v-for="row in srLadder"
                  :key="row.key"
                  class="sr-rung"
                  :class="{
                    hot: hoveredLevelKey === row.key,
                    support: row.support,
                    resistance: !row.support,
                  }"
                  @mouseenter="hoveredLevelKey = row.key"
                  @mouseleave="hoveredLevelKey = null"
                >
                  <span class="sr-kind">{{ row.label }}</span>
                  <b class="fig sr-px">{{ fmtPrice(row.level.price) }}</b>
                  <span class="fig sr-dist">{{ row.distLabel }}</span>
                  <span class="fig sr-touch">{{ fmtInt(row.level.touches) }}×</span>
                  <span v-if="row.level.role_reversed" class="rr-tag">role reversed</span>
                </li>
              </ol>

              <!-- Volume-at-price readouts -->
              <div class="vap-strip">
                <div class="vap-cell">
                  <span class="label">Point of control</span>
                  <span class="vap-val fig warn">{{ fmtPrice(vap?.poc) }}</span>
                  <span
                    v-if="typeof vap?.poc_low === 'number' && typeof vap?.poc_high === 'number'"
                    class="vap-sub fig"
                    >band {{ fmtNum(vap.poc_low) }}–{{ fmtNum(vap.poc_high) }}</span
                  >
                </div>
                <div class="vap-cell">
                  <span class="label">Value area low</span>
                  <span class="vap-val fig">{{ fmtPrice(vap?.value_area_low) }}</span>
                </div>
                <div class="vap-cell">
                  <span class="label">Value area high</span>
                  <span class="vap-val fig">{{ fmtPrice(vap?.value_area_high) }}</span>
                </div>
                <div class="vap-cell">
                  <span class="label">Value area coverage</span>
                  <span class="vap-val fig">{{
                    typeof vap?.value_area_pct === 'number'
                      ? `${(vap.value_area_pct * 100).toFixed(1)}%`
                      : DASH
                  }}</span>
                  <span class="vap-sub fig">of {{ fmtInt(vap?.total_volume) }} shares</span>
                </div>
                <div class="vap-cell">
                  <span class="label">Profile bins</span>
                  <span class="vap-val fig">{{ fmtInt(vap?.bins?.length) }}</span>
                  <span v-if="typeof vap?.bin_size === 'number'" class="vap-sub fig"
                    >{{ fmtNum(vap.bin_size) }} wide</span
                  >
                </div>
                <div class="vap-cell">
                  <span class="label">ATR (served bars)</span>
                  <span class="vap-val fig">{{ fmtNum(atr) }}</span>
                  <span v-if="vap?.method" class="vap-sub">{{
                    vap.method.replace(/_/g, ' ')
                  }}</span>
                </div>
              </div>

              <!-- Numeric, drawable levels -->
              <div v-if="orderedLevels.length" class="table-frame">
                <table class="vpa-table levels-table">
                  <thead>
                    <tr>
                      <th>Zone</th>
                      <th class="num">Price</th>
                      <th class="num">Band</th>
                      <th class="num">Touches</th>
                      <th class="num">Strength</th>
                      <th>Origin</th>
                      <th class="num">Last touch</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(l, idx) in orderedLevels"
                      :key="levelKey(l, idx)"
                      class="level-row"
                      :class="{
                        hot: hoveredLevelKey === levelKey(l, idx),
                        support: /support/i.test(l.kind),
                        resistance: /resist/i.test(l.kind),
                      }"
                      @mouseenter="hoveredLevelKey = levelKey(l, idx)"
                      @mouseleave="hoveredLevelKey = null"
                    >
                      <td class="td-name">
                        <i class="lvl-dot"></i>
                        {{ levelKindLabel(l.kind) }}
                        <span
                          v-if="l.role_reversed"
                          class="rr-tag"
                          title="A ceiling closed through on rising volume can later act as support"
                          >role reversed</span
                        >
                      </td>
                      <td class="num fig td-strong">{{ fmtPrice(l.price) }}</td>
                      <td class="num fig td-dim">{{ fmtNum(l.low) }}–{{ fmtNum(l.high) }}</td>
                      <td class="num fig">{{ fmtInt(l.touches) }}</td>
                      <td class="num">
                        <span class="strength-cell">
                          <i
                            class="strength-fill"
                            :style="{ width: `${clamp01(l.strength ?? 0) * 100}%` }"
                          ></i>
                          <span class="fig strength-num">{{ fmtNum(l.strength, 2) }}</span>
                        </span>
                      </td>
                      <td class="td-dim" :title="fmtText(l.source)">
                        {{ levelOriginLabel(l) }}
                      </td>
                      <td class="num fig td-dim">
                        <template v-if="levelBarsSinceTouch(l) !== null"
                          >{{ levelBarsSinceTouch(l) }} bars ago</template
                        >
                        <template v-else>{{ DASH }}</template>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p v-else class="empty-note">
                No numeric levels in this response. Nothing has been drawn on the chart: the engine
                did not report a <code>levels[]</code> set.
              </p>

              <!-- Engine prose summary — structured, always visible -->
              <div
                v-if="analysisResult.forensic_breakdown.support_resistance"
                class="legacy-sr prose-sr"
              >
                <div class="legacy-head label">Engine prose summary</div>
                <div class="legacy-grid">
                  <div>
                    <span class="label">Ceiling of resistance</span>
                    <span class="legacy-val neg">{{
                      fmtText(
                        analysisResult.forensic_breakdown.support_resistance.ceiling_resistance,
                      )
                    }}</span>
                  </div>
                  <div>
                    <span class="label">Floor of support</span>
                    <span class="legacy-val pos">{{
                      fmtText(analysisResult.forensic_breakdown.support_resistance.floor_support)
                    }}</span>
                  </div>
                  <div>
                    <span class="label">Pivot highs</span>
                    <span class="legacy-val fig neg">{{
                      fmtText(analysisResult.forensic_breakdown.support_resistance.pivot_highs)
                    }}</span>
                  </div>
                  <div>
                    <span class="label">Pivot lows</span>
                    <span class="legacy-val fig pos">{{
                      fmtText(analysisResult.forensic_breakdown.support_resistance.pivot_lows)
                    }}</span>
                  </div>
                  <div class="legacy-wide">
                    <span class="label">Volume at price</span>
                    <span class="legacy-val">{{
                      fmtText(analysisResult.forensic_breakdown.volume_at_price)
                    }}</span>
                  </div>
                  <div v-if="srMethod" class="legacy-wide">
                    <span class="label">Derivation</span>
                    <span class="legacy-val">{{ srMethod }}</span>
                  </div>
                </div>
              </div>
            </section>

            <!-- How the confidence headline was built, and where the thresholds came from -->
            <section class="forensic-section">
              <h4 class="section-title">
                <AppIcon name="gate" :size="15" />
                <span>Read Quality &amp; Threshold Provenance</span>
                <span class="title-sub">the confidence number, decomposed</span>
              </h4>

              <div v-if="confidenceComponents.length" class="quality-panel">
                <div class="quality-head">
                  <div class="quality-score">
                    <span
                      class="fig quality-fig"
                      :class="confidencePct === null ? 'flat' : 'pos'"
                      >{{ confidencePct === null ? DASH : `${confidencePct}%` }}</span
                    >
                    <span class="label">Confidence</span>
                  </div>
                  <div class="quality-reads">
                    <span class="quality-read">
                      <span class="label">Bars read</span>
                      <b class="fig">{{ fmtInt(confidenceBarCount) }}</b>
                    </span>
                    <span class="quality-read">
                      <span class="label">Data age</span>
                      <b class="fig">{{ fmtNum(confidenceDataAge, 1) }}d</b>
                    </span>
                  </div>
                </div>

                <ul class="quality-list">
                  <li v-for="c in confidenceComponents" :key="c.key" class="quality-row">
                    <span class="quality-label">{{ c.label }}</span>
                    <span class="quality-track">
                      <i
                        class="quality-fill"
                        :class="{ weak: (c.value ?? 0) < 0.6 }"
                        :style="{ width: `${clamp01(c.value ?? 0) * 100}%` }"
                      ></i>
                    </span>
                    <span class="fig quality-num">{{ fmtNum(c.value, 2) }}</span>
                  </li>
                </ul>

                <p v-if="confidenceBasis?.method" class="quality-method">
                  {{ confidenceBasis.method }}
                </p>
              </div>
              <p v-else class="empty-note">
                This response carried no <code>confidence_basis</code>. The confidence figure above
                is therefore unaudited: treat it as an assertion, not a measurement.
              </p>

              <div v-if="thresholdsStatus" class="thresholds-bar">
                <span
                  class="status-chip"
                  :class="thresholdsStatus.provisional ? 'chip-warn' : 'chip-pos'"
                  >{{
                    thresholdsStatus.provisional ? 'Provisional defaults' : 'Book-derived'
                  }}</span
                >
                <span class="thresholds-src fig">{{
                  fmtText(thresholdsStatus.thresholds_source ?? thresholdsStatus.spec_path)
                }}</span>
                <span v-if="thresholdsStatus.note" class="thresholds-note">{{
                  thresholdsStatus.note
                }}</span>
              </div>
            </section>
          </div>

          <!-- Tab Content 2: Scenarios & Speculative Alternatives -->
          <div v-if="selectedTab === 'scenarios'" class="tab-pane">
            <!-- Primary Scenario -->
            <div class="scenario-card primary">
              <div class="scenario-header">
                <div class="sh-left">
                  <span class="badge-primary">Primary Read</span>
                  <span class="sh-move" :class="directionColorClass">{{
                    fmtText(analysisResult.primary_scenario.likely_move)
                  }}</span>
                </div>
                <div class="prob-block">
                  <div class="prob-figure fig">
                    {{ fmtPct(analysisResult.primary_scenario.probability_pct) }}
                  </div>
                  <div class="prob-caption label">Likelihood</div>
                </div>
              </div>

              <!-- probability_basis: how the percentage was formed -->
              <div v-if="probabilityBasis" class="basis-strip">
                <div class="basis-scores">
                  <span class="basis-item">
                    <span class="label">Bull score</span>
                    <b class="fig pos">{{ fmtNum(probabilityBasis.bull_score) }}</b>
                  </span>
                  <span class="basis-item">
                    <span class="label">Bear score</span>
                    <b class="fig neg">{{ fmtNum(probabilityBasis.bear_score) }}</b>
                  </span>
                  <span class="basis-item">
                    <span class="label">Method</span>
                    <b class="fig">{{ fmtText(probabilityBasis.method) }}</b>
                  </span>
                  <span class="basis-item">
                    <span class="label">Clamp</span>
                    <b class="fig">{{
                      probabilityBasis.band?.length === 2
                        ? `${probabilityBasis.band[0]}–${probabilityBasis.band[1]}%`
                        : DASH
                    }}</b>
                  </span>
                  <!-- A clamped figure sits on the band edge: the evidence ran
                       past the scale, so the percentage understates it. -->
                  <span class="basis-item">
                    <span class="label">Raw / evidence</span>
                    <b class="fig" :class="{ warn: probabilityBasis.clamped }">
                      {{ fmtPct(probabilityBasis.raw_probability_pct) }}
                      <template v-if="probabilityBasis.clamped"> · clamped</template>
                      <template v-if="typeof probabilityBasis.evidence_count === 'number'">
                        · {{ probabilityBasis.evidence_count }} signals
                      </template>
                    </b>
                  </span>
                </div>
                <p class="basis-note">
                  {{
                    probabilityBasis.note ||
                    'VPA is directional evidence, not a calibrated forecast.'
                  }}
                </p>
                <!--
                  Measured, not assumed. A walk-forward over 60 symbols with a
                  chronological split found no edge over a skill-free caller.
                  Hiding that would make this number look predictive when the
                  evidence says it is not.
                -->
                <p class="basis-validation">
                  <AppIcon name="alert" :size="11" />
                  <span>
                    Walk-forward validated: over 60 symbols with a chronological in/out-of-sample
                    split, this percentage showed <b>no measurable edge</b> over a skill-free caller
                    once market drift is accounted for, and its buckets are not monotonic. Use it to
                    rank the weight of evidence, never as a forecast. See
                    <code>docs/VPA_VALIDATION.md</code>.
                  </span>
                </p>
              </div>
              <p v-else class="basis-missing">
                No <code>probability_basis</code> in this response: this percentage arrives without
                the scores that produced it. Read it as an unsupported claim.
              </p>

              <div class="primary-grid">
                <div>
                  <span class="label">Target zone</span>
                  <span class="pg-val fig">{{
                    fmtText(analysisResult.primary_scenario.target_zone)
                  }}</span>
                </div>
                <div>
                  <span class="label">Cause &amp; effect horizon</span>
                  <span class="pg-val">{{
                    fmtText(analysisResult.primary_scenario.expected_horizon)
                  }}</span>
                </div>
              </div>

              <div class="rationale">
                <span class="label">Forensic rationale</span>
                <p>{{ fmtText(analysisResult.primary_scenario.rationale) }}</p>
              </div>
            </div>

            <!-- Evidence ledger: the antidote to "the numbers look made up" -->
            <section class="evidence-section">
              <h4 class="section-title">
                <AppIcon name="research" :size="15" />
                <span>Evidence Ledger</span>
                <span class="title-sub">every signal behind the percentage, with its citation</span>
              </h4>

              <div v-if="orderedEvidence.length" class="evidence-list">
                <article
                  v-for="(ev, idx) in orderedEvidence"
                  :key="`${ev.signal}-${idx}`"
                  class="evidence-row"
                  :class="[
                    evidenceDirClass(ev.direction),
                    { selected: selectedEvidenceIdx === idx },
                  ]"
                  role="button"
                  tabindex="0"
                  :aria-pressed="selectedEvidenceIdx === idx"
                  @click="selectEvidence(idx)"
                  @keydown.enter.prevent="selectEvidence(idx)"
                >
                  <div class="ev-dir">
                    <i class="ev-dot"></i>
                    <span class="ev-dir-text label">{{ ev.direction }}</span>
                  </div>
                  <div class="ev-main">
                    <div class="ev-head">
                      <span class="ev-signal">{{ ev.signal.replace(/_/g, ' ') }}</span>
                      <span v-if="ev.book_ref" class="ev-cite">{{ ev.book_ref }}</span>
                    </div>
                    <p v-if="ev.detail" class="ev-detail">{{ ev.detail }}</p>
                    <div v-if="ev.bars?.length" class="ev-locus fig">
                      <span class="ev-bars">{{ evidenceBarRange(ev) }}</span>
                      <span class="ev-px">{{ evidencePriceWindow(ev) }}</span>
                      <span class="ev-idx">bars {{ ev.bars.join(', ') }}</span>
                    </div>
                  </div>
                  <div class="ev-weight">
                    <div class="ev-weight-track">
                      <i class="ev-weight-fill" :style="{ width: evidenceBarWidth(ev.weight) }"></i>
                    </div>
                    <span class="fig ev-weight-num">{{ fmtNum(ev.weight, 2) }}</span>
                  </div>
                </article>
              </div>
              <p v-else class="empty-note">
                This response carried no <code>evidence[]</code> ledger. Without it the probability
                above is a bare assertion: there is nothing here to audit.
              </p>
            </section>

            <!-- Speculative Alternative Reads -->
            <div class="alt-block">
              <div class="alt-head">
                <h4 class="label">Speculative Alternative Reads &amp; Invalidation</h4>
                <span class="alt-caution">Caution: Market Reading is Discretionary</span>
              </div>
              <p
                v-if="scenarioProbabilitySum !== null && Math.abs(scenarioProbabilitySum - 100) > 1"
                class="alt-sumwarn"
              >
                Scenario probabilities sum to
                <b class="fig">{{ scenarioProbabilitySum }}%</b>, not 100%.
              </p>

              <div
                v-for="(alt, idx) in analysisResult.alternative_scenarios"
                :key="idx"
                class="scenario-card alternative"
              >
                <div class="scenario-header">
                  <div class="sh-left">
                    <span class="badge-alt">Alt #{{ idx + 1 }}</span>
                    <span class="sh-move">{{ fmtText(alt.thesis) }}</span>
                  </div>
                  <div class="prob-block">
                    <div class="prob-figure fig alt">{{ fmtPct(alt.probability_pct) }}</div>
                    <div class="prob-caption label">Probability</div>
                  </div>
                </div>

                <p class="alt-read">{{ fmtText(alt.speculative_read) }}</p>

                <!-- Invalidation Trigger -->
                <div class="invalidation-box">
                  <div class="inv-title">Exact Invalidation Trigger:</div>
                  <div class="inv-val fig">{{ fmtText(alt.invalidation_trigger) }}</div>
                </div>

                <p v-if="alt.risk_warning" class="alt-risk">{{ alt.risk_warning }}</p>
              </div>
            </div>
          </div>

          <!-- Tab Content 3: Trade Execution & Risk Management -->
          <div v-if="selectedTab === 'execution'" class="tab-pane">
            <div class="execution-card">
              <div
                v-if="riskLadder"
                class="risk-ladder exec-rail"
                role="img"
                :aria-label="`Price staff, high at top. ${riskLadder.rungs.map((r) => `${r.label} ${fmtPrice(r.price)}`).join('. ')}`"
              >
                <div class="rl-head">
                  <span class="label">Price staff</span>
                  <span class="rl-span fig"
                    >{{ fmtPrice(riskLadder.hi) }} → {{ fmtPrice(riskLadder.lo) }}</span
                  >
                </div>
                <ol class="rl-rungs">
                  <li
                    v-for="rung in riskLadder.rungs"
                    :key="'exec-' + rung.label + rung.price"
                    class="rl-rung"
                    :class="[`tone-${rung.tone}`, { 'is-entry': rung.isEntry }]"
                  >
                    <span class="rl-roles">{{ rung.label }}</span>
                    <span class="rl-tick" aria-hidden="true">
                      <i v-if="rung.segBelow" class="rl-seg" :class="`seg-${rung.segBelow}`" />
                    </span>
                    <b class="rl-px fig">{{ fmtPrice(rung.price) }}</b>
                    <span class="rl-delta fig">{{ rung.deltaLabel }}</span>
                  </li>
                </ol>
                <div class="rl-foot fig">
                  <span class="rl-risk">Risk {{ fmtNum(riskLadder.risk) }}</span>
                  <span class="cr-sep">·</span>
                  <span class="rl-reward">Reward {{ fmtNum(riskLadder.reward) }}</span>
                </div>
              </div>
              <div class="exec-grid">
                <div class="exec-col">
                  <span class="label">Directional Bias</span>
                  <span class="exec-val" :class="directionColorClass">{{
                    fmtText(analysisResult.trade_execution_guide.bias)
                  }}</span>
                </div>
                <div class="exec-col">
                  <span class="label">Risk : Reward</span>
                  <span class="exec-val fig" :class="riskReward === DASH ? 'flat' : 'pos'">{{
                    riskReward
                  }}</span>
                  <span v-if="riskReward === DASH" class="exec-hint">{{
                    analysisResult.trade_execution_guide.risk_reward_unavailable_reason ||
                    'entry, stop or target not derivable'
                  }}</span>
                </div>
              </div>

              <!-- The three levels the ratio is actually computed from. -->
              <div v-if="hasTradeLevels" class="level-triplet">
                <div class="lt-cell">
                  <span class="label">Entry</span>
                  <span class="fig lt-val">{{
                    fmtPrice(analysisResult.trade_execution_guide.entry_price)
                  }}</span>
                </div>
                <div class="lt-cell">
                  <span class="label">Stop</span>
                  <span class="fig lt-val neg">{{
                    fmtPrice(analysisResult.trade_execution_guide.stop_price)
                  }}</span>
                  <span v-if="tradeRiskPerUnit !== null" class="lt-sub fig"
                    >risk {{ fmtNum(tradeRiskPerUnit) }}</span
                  >
                </div>
                <div class="lt-cell">
                  <span class="label">Target</span>
                  <span class="fig lt-val pos">{{
                    fmtPrice(analysisResult.trade_execution_guide.target_price)
                  }}</span>
                  <span v-if="tradeRewardPerUnit !== null" class="lt-sub fig"
                    >reward {{ fmtNum(tradeRewardPerUnit) }}</span
                  >
                </div>
              </div>

              <div class="exec-details">
                <div class="exec-detail-row">
                  <span class="label">Entry Trigger Condition</span>
                  <span class="detail-val">{{
                    fmtText(analysisResult.trade_execution_guide.entry_trigger)
                  }}</span>
                </div>
                <div class="exec-detail-row">
                  <span class="label">Stop placement</span>
                  <span class="detail-val fig neg">{{
                    fmtText(analysisResult.trade_execution_guide.stop_loss_placement)
                  }}</span>
                </div>
              </div>

              <div class="rules-block">
                <span class="label">Rules applied</span>
                <ul class="rules-list">
                  <li
                    v-for="(rule, rIdx) in analysisResult.trade_execution_guide.rules_applied"
                    :key="rIdx"
                  >
                    {{ rule }}
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="empty-state">
          <AppIcon name="vpa" :size="48" class="es-icon" />
          <h3 class="es-title">No Active Chart Analysis</h3>
          <p class="es-body">
            Enter a ticker above, or paste a screenshot with ⌘V. The read is computed from bars.
          </p>
        </div>
      </div>
    </div>

    <!-- Volume-price rules drawer -->
    <div v-if="codexDrawerOpen" class="codex-drawer-backdrop" @click="codexDrawerOpen = false">
      <div class="codex-drawer" @click.stop>
        <div class="drawer-header">
          <div>
            <h2 class="drawer-title">Volume-price rules</h2>
            <p class="drawer-sub">Foundational laws, principles &amp; schematics</p>
          </div>
          <button
            class="close-drawer-btn"
            aria-label="Close codex"
            @click="codexDrawerOpen = false"
          >
            ✕
          </button>
        </div>

        <div v-if="codex" class="drawer-body">
          <!-- Wyckoff Laws -->
          <section class="codex-section">
            <h3 class="codex-sec-title">Three Universal Laws (Wyckoff)</h3>
            <div class="codex-stack">
              <div v-for="law in codex.laws" :key="law.id" class="codex-card">
                <div class="cc-title">{{ law.name }}</div>
                <div class="cc-body">{{ law.principle }}</div>
                <div class="cc-app">VPA application: {{ law.vpa_application }}</div>
              </div>
            </div>
          </section>

          <!-- Core Principles -->
          <section class="codex-section">
            <h3 class="codex-sec-title">Core Operating Principles</h3>
            <div class="codex-stack">
              <div v-for="p in codex.principles" :key="p.number" class="codex-card">
                <div class="cc-title ink">{{ p.number }}. {{ p.name }}</div>
                <div class="cc-body">{{ p.summary }}</div>
              </div>
            </div>
          </section>

          <!-- Textbook cases moved out of the side rail -->
          <section class="codex-section">
            <h3 class="codex-sec-title">
              Reference cases
              <span class="ref-badge">Reference library</span>
            </h3>
            <p class="ref-preamble">
              Third-party published chart commentaries are not included. This list stays empty
              unless a stored reference case is returned by the API.
            </p>
            <div class="reference-list">
              <button
                v-for="sample in sampleList"
                :key="sample.id"
                class="reference-item"
                :class="{ active: isReferenceCase && analysisResult?.symbol === sample.symbol }"
                @click="
                  loadSample(sample.id);
                  codexDrawerOpen = false;
                "
              >
                <span class="ri-spine"></span>
                <span class="ri-body">
                  <span class="ri-top">
                    <span class="ri-symbol fig">{{ sample.symbol }}</span>
                    <span class="ri-tf fig">{{ sample.timeframe }}</span>
                  </span>
                  <span class="ri-title">{{ sample.title }}</span>
                  <span class="ri-cite">{{ sample.book_reference }}</span>
                  <span v-if="sample.description" class="ri-desc">{{ sample.description }}</span>
                </span>
              </button>
              <p v-if="sampleList.length === 0" class="ref-empty">
                No reference cases returned by <code>/api/vpa/samples</code>.
              </p>
            </div>
          </section>

          <!-- Candle Taxonomy -->
          <section class="codex-section">
            <h3 class="codex-sec-title">Premier Candlestick Taxonomies</h3>
            <div class="codex-stack">
              <div v-for="c in codex.candle_taxonomy" :key="c.name" class="codex-card">
                <div class="cc-head">
                  <span class="cc-title">{{ c.name }}</span>
                  <span class="cc-cat label">{{ c.category }}</span>
                </div>
                <div class="cc-body">{{ c.structure }}</div>
                <dl class="cc-scenarios">
                  <div v-for="(vText, vKey) in c.volume_scenarios" :key="vKey">
                    <dt class="fig">{{ vKey }}</dt>
                    <dd>{{ vText }}</dd>
                  </div>
                </dl>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===========================================================================
   VPA workspace — typography follows the desk ladder in styles/tokens.css:
   micro 11 / tiny 12 / small 13 / body 14 / lead 16 / fig 22.
   Weight ladder: 400 prose · 500 emphasis · 600 UI + labels · 650/700 figures.
   Every price, percentage and count carries tabular figures via .fig.
   ======================================================================== */

.vpa-view-root {
  padding: var(--s5);
  max-width: 1600px;
  margin: 0 auto;
  font-family: var(--font-ui);
  font-size: var(--t-small);
  color: var(--ink-soft);
}

.fig {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum', 'zero';
  letter-spacing: var(--track-tight);
}

.phos {
  color: var(--phosphor);
}
.warn {
  color: var(--warn);
}

/* ---- header ------------------------------------------------------------ */

.vpa-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--s4);
  margin-bottom: var(--s4);
  padding-bottom: var(--s3);
  border-bottom: 1px solid var(--rule);
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
  min-width: 0;
}

.icon-frame {
  width: 38px;
  height: 38px;
  flex: none;
  border-radius: var(--r-sm);
  background: var(--phosphor-wash);
  color: var(--phosphor);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--phosphor-dim);
}

.title-block {
  min-width: 0;
}

.title-row {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.view-title {
  font-family: var(--font-display);
  font-size: var(--t-display);
  font-weight: 650;
  letter-spacing: var(--track-display);
  line-height: 1.15;
  color: var(--ink);
  margin: 0;
}

.view-subtitle {
  margin: 5px 0 0;
  font-size: var(--t-small);
  line-height: 1.55;
  color: var(--ink-dim);
  max-width: 76ch;
}

.version-pill,
.engine-pill,
.ref-badge {
  font-size: var(--t-micro);
  font-weight: 600;
  line-height: 1.4;
  padding: 1px 7px;
  border-radius: var(--r-capsule);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  white-space: nowrap;
}

.version-pill {
  background: var(--panel);
  color: var(--ink-dim);
  border: 1px solid var(--rule);
}

.engine-pill {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
  text-transform: none;
  letter-spacing: 0;
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex: none;
}

.mode-toggle-group {
  display: flex;
  background: var(--void-lift);
  border: 1px solid var(--rule-hi);
  border-radius: var(--r-sm);
  padding: 2px;
}

.mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--t-tiny);
  font-weight: 600;
  padding: 5px 10px;
  border-radius: var(--r-xs);
  color: var(--ink-dim);
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  white-space: nowrap;
}
.mode-btn:hover {
  color: var(--ink);
}
.mode-btn.active {
  background: var(--panel-raise);
  color: var(--phosphor);
  border-color: var(--rule-hi);
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--t-tiny);
  font-weight: 600;
  padding: 7px 13px;
  border-radius: var(--r-sm);
  cursor: pointer;
  white-space: nowrap;
  transition:
    background 0.15s ease,
    color 0.15s ease;
}

.codex-btn {
  background: var(--panel-raise);
  color: var(--ink);
  border: 1px solid var(--rule-hi);
}
.codex-btn:hover {
  background: var(--panel-hi);
}

.clear-btn {
  background: transparent;
  color: var(--ink-dim);
  border: 1px solid var(--rule);
}
.clear-btn:hover {
  color: var(--short);
}

/* ---- banners ----------------------------------------------------------- */

.alert-banner {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  padding: 9px 13px;
  border-radius: var(--r-sm);
  font-size: var(--t-tiny);
  line-height: 1.55;
  margin-bottom: var(--s2);
}
.alert-banner span:last-child {
  max-width: 110ch;
}
.banner-tag {
  flex: none;
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}
.alert-banner.neg-banner {
  background: var(--short-wash);
  color: var(--short);
  border: 1px solid var(--short);
}
.alert-banner.notice-banner {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border: 1px solid var(--phosphor-dim);
}
.alert-banner.warn-banner {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}

/* ---- layout ------------------------------------------------------------ */

.vpa-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s4);
  align-items: start;
  margin-top: var(--s3);
}

.vpa-col-left,
.vpa-col-right {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  min-width: 0;
}

.vpa-card {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-lg);
  padding: var(--s4);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s2);
  margin-bottom: var(--s3);
}

/* ---- chart controls ---------------------------------------------------- */

.desk-controls {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s2);
  margin: var(--s3) 0 var(--s2);
}
.desk-controls .symbol-main-input {
  width: 118px;
  flex: none;
}
.desk-controls .quick-chips-row {
  margin-top: 0;
  width: 100%;
}
.lookback-unit {
  color: var(--ink-dim);
}
.seg {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  border: 1px solid var(--rule);
  border-radius: var(--r-xs);
  overflow: hidden;
}
.seg-btn {
  min-height: 28px;
  padding: 3px 10px;
  color: var(--ink-dim);
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.seg-btn:hover:not(:disabled) {
  color: var(--ink);
  background: var(--panel-hi);
}
.seg-btn.on {
  color: var(--phosphor);
  background: var(--phosphor-wash);
}
.seg-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.seg-fallback {
  padding: 0 10px;
  color: var(--warn);
  font-size: var(--t-micro);
  line-height: 28px;
}
.desk-controls .field-select {
  height: 28px;
  flex: none;
  max-width: 160px;
  background: var(--void-lift);
  border: 1px solid var(--rule-hi);
  color: var(--ink);
  font-size: var(--t-micro);
  padding: 0 8px;
}
.tf-native {
  display: none;
}

.window-group {
  display: flex;
  gap: 4px;
}

.window-btn {
  font-size: var(--t-micro);
  font-weight: 600;
  padding: 3px 8px;
  border-radius: var(--r-xs);
  background: var(--void-lift);
  color: var(--ink-dim);
  border: 1px solid var(--rule);
  cursor: pointer;
}
.window-btn:hover {
  color: var(--ink);
}
.window-btn.active {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.symbol-search-bar {
  display: flex;
  gap: var(--s2);
}

.symbol-main-input {
  flex: 1;
  min-width: 0;
  background: var(--void-lift);
  border: 1px solid var(--rule-hi);
  color: var(--ink);
  font-size: var(--t-body);
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 7px 11px;
  border-radius: var(--r-sm);
  text-transform: uppercase;
}
.symbol-main-input::placeholder {
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--ink-dim);
}
.symbol-main-input:focus {
  outline: none;
  border-color: var(--phosphor);
}

.fetch-btn {
  background: var(--phosphor);
  color: var(--void);
  font-size: var(--t-tiny);
  font-weight: 650;
  padding: 7px 16px;
  border-radius: var(--r-sm);
  border: none;
  cursor: pointer;
  white-space: nowrap;
}
.fetch-btn:hover:not(:disabled) {
  background: var(--phosphor-dim);
}
.fetch-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.quick-chips-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: var(--s2);
}

.chip-btn {
  font-size: var(--t-micro);
  font-weight: 600;
  padding: 3px 7px;
  border-radius: var(--r-xs);
  background: var(--void-lift);
  color: var(--ink-dim);
  border: 1px solid var(--rule);
  cursor: pointer;
}
.chip-btn:hover {
  color: var(--ink);
  border-color: var(--rule-hi);
}
.chip-btn.active {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}

.chart-card {
  padding-bottom: var(--s3);
}
.chart-meta {
  color: var(--ink-dim);
  font-size: var(--t-micro);
}
.chart-host {
  position: relative;
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  height: 440px;
  overflow: hidden;
  margin-top: var(--s2);
}
.vpa-svg {
  width: 100%;
  height: 100%;
  display: block;
  cursor: crosshair;
}
.chart-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-dim);
  font-size: var(--t-tiny);
  margin: 0;
}
.grid-line {
  stroke: var(--rule);
  stroke-width: 1;
}
.axis-label {
  fill: var(--ink-faint);
  font-size: 10px;
  font-family: var(--font-data);
}
.va-fill {
  fill: var(--phosphor);
  fill-opacity: 0.07;
}
.lvl-zone {
  fill: var(--short);
}
.lvl-band.is-sup .lvl-zone {
  fill: var(--long);
}
.lvl-edge {
  stroke: var(--short);
  stroke-width: 1.2;
}
.lvl-band.is-sup .lvl-edge {
  stroke: var(--long);
}
.lvl-edge.dashed {
  stroke-dasharray: 6 3;
}
.lvl-tag {
  fill: var(--short);
  font-size: 10px;
  font-family: var(--font-data);
  paint-order: stroke fill;
  stroke: var(--panel);
  stroke-width: 3px;
  stroke-linejoin: round;
}
.lvl-band.is-sup .lvl-tag {
  fill: var(--long);
}
.lvl-band.hot .lvl-edge {
  stroke-width: 2;
}
.vap-bar {
  fill: var(--phosphor);
  fill-opacity: 0.16;
}
.vap-bar.in {
  fill-opacity: 0.32;
}
.vap-bar.poc {
  fill: var(--warn);
  fill-opacity: 0.45;
}
.ev-mark {
  fill: var(--phosphor);
  fill-opacity: 0.16;
}
.candle-wick {
  stroke: var(--ink-soft);
  stroke-width: 1.1;
  fill: none;
}
.candle-up {
  fill: var(--call-hi);
}
.candle-down {
  fill: var(--short);
}
.poc-line {
  stroke: var(--warn);
  stroke-width: 1.6;
}
.poc-label {
  fill: var(--warn);
  font-size: 10px;
  paint-order: stroke fill;
  stroke: var(--panel);
  stroke-width: 3px;
  stroke-linejoin: round;
}
.last-line {
  stroke: var(--ink);
  stroke-width: 1;
  stroke-dasharray: 3 3;
  stroke-opacity: 0.45;
}
.trade-line {
  stroke-width: 1.2;
  stroke-dasharray: 4 3;
}
.trade-line.tl-entry {
  stroke: var(--phosphor);
}
.trade-line.tl-stop {
  stroke: var(--short);
}
.trade-line.tl-target {
  stroke: var(--long);
}
.trade-label {
  font-size: 10px;
  paint-order: stroke fill;
  stroke: var(--panel);
  stroke-width: 3px;
  stroke-linejoin: round;
}
.trade-label.tl-entry {
  fill: var(--phosphor);
}
.trade-label.tl-stop {
  fill: var(--short);
}
.trade-label.tl-target {
  fill: var(--long);
}
.vol-bar {
  fill-opacity: 0.45;
}
.vol-bar.up {
  fill: var(--call-wash);
}
.vol-bar.down {
  fill: var(--short-wash);
}
.vol-bar.live {
  fill-opacity: 0.8;
  stroke: var(--warn);
  stroke-width: 0.6;
}
.vol-sma {
  fill: none;
  stroke: var(--ink);
  stroke-width: 1.2;
}

.chart-canvas-wrap {
  position: relative;
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  height: 320px;
  overflow: hidden;
  margin-top: var(--s3);
}

.vpa-canvas {
  width: 100%;
  height: 100%;
  display: block;
  cursor: crosshair;
}

.canvas-tooltip {
  position: absolute;
  pointer-events: none;
  background: var(--panel-raise);
  border: 1px solid var(--rule-hi);
  padding: 6px 9px;
  border-radius: var(--r-xs);
  z-index: 10;
  box-shadow: var(--shadow-2);
}
.tt-date {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  color: var(--phosphor);
}
.tt-row {
  font-size: var(--t-micro);
  margin-top: 3px;
  color: var(--ink);
}
.tt-row span {
  color: var(--ink-dim);
  margin-right: 4px;
}
.tt-row b {
  font-weight: 600;
  margin-right: 8px;
}
.tt-vol {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  margin-top: 3px;
}

.chart-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s3);
  margin-top: var(--s2);
  font-size: var(--t-tiny);
  color: var(--ink-dim);
}
.lg-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.sw {
  width: 12px;
  height: 8px;
  border-radius: 2px;
  display: inline-block;
}
.sw-sup {
  background: var(--long-wash);
  border-top: 1.5px solid var(--long);
}
.sw-res {
  background: var(--short-wash);
  border-top: 1.5px solid var(--short);
}
.sw-poc {
  height: 0;
  border-top: 2px solid var(--warn);
}
.sw-va {
  background: var(--phosphor-glow);
  border: 1px solid var(--phosphor-dim);
}
.sw-rr {
  height: 0;
  border-top: 2px dashed var(--ink-dim);
}
.lg-empty {
  color: var(--ink-dim);
  font-style: italic;
}

.under-canvas {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s2);
  margin-top: var(--s3);
}
.uc-meta {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.snap-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--void-lift);
  color: var(--ink-dim);
  border: 1px solid var(--rule);
  padding: 5px 10px;
  border-radius: var(--r-xs);
  font-size: var(--t-micro);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.snap-btn:hover:not(:disabled) {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.snap-btn:disabled,
.snap-btn.is-blocked {
  opacity: 0.55;
  cursor: not-allowed;
  color: var(--ink-faint);
  border-style: dashed;
}
.snap-reason {
  margin: 6px 0 0;
  font-size: var(--t-micro);
  line-height: 1.5;
  color: var(--warn);
  text-align: right;
}

/* ---- upload / dropzone ------------------------------------------------- */

.upload-card {
  background: var(--panel);
  border: 2px dashed var(--rule-hi);
  border-radius: var(--r-lg);
  padding: var(--s4);
  min-height: 230px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.upload-card.is-dragging {
  border-color: var(--phosphor);
  background: var(--phosphor-wash);
}
.upload-card.has-image {
  border-style: solid;
  border-color: var(--rule);
  padding: 0;
  overflow: hidden;
}

.dropzone-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.paste-icon-box {
  width: 58px;
  height: 58px;
  border-radius: var(--r-content);
  background: var(--void-lift);
  color: var(--phosphor);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--s3);
  border: 1px solid var(--rule);
}

.dz-title {
  font-size: var(--t-body);
  font-weight: 600;
  color: var(--ink);
  margin: 0;
  letter-spacing: var(--track-tight);
}
.dz-body {
  font-size: var(--t-tiny);
  line-height: 1.6;
  color: var(--ink-dim);
  margin: 6px 0 0;
  max-width: 48ch;
}
.dz-warn {
  font-size: var(--t-micro);
  line-height: 1.5;
  color: var(--warn);
  margin: var(--s2) 0 0;
  max-width: 52ch;
}
.dz-actions {
  margin-top: var(--s4);
}

.file-upload-label {
  cursor: pointer;
  background: var(--panel-raise);
  color: var(--ink-soft);
  padding: 6px 14px;
  border-radius: var(--r-sm);
  font-size: var(--t-tiny);
  font-weight: 600;
  border: 1px solid var(--rule-hi);
}
.file-upload-label:hover {
  color: var(--ink);
  background: var(--panel-hi);
}

.hidden-input {
  display: none;
}

.chart-preview-container {
  display: flex;
  flex-direction: column;
  background: var(--void);
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 11px;
  background: var(--panel);
  border-bottom: 1px solid var(--rule);
}
.ph-left {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: var(--t-tiny);
}
.ph-sym {
  font-weight: 700;
  color: var(--phosphor);
  letter-spacing: 0.04em;
}
.ph-sep {
  color: var(--ink-dim);
}
.ph-tf {
  color: var(--ink-soft);
}

.change-file-btn {
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-dim);
  cursor: pointer;
}
.change-file-btn:hover {
  color: var(--phosphor);
}

.preview-body {
  padding: var(--s2);
  display: flex;
  align-items: center;
  justify-content: center;
  max-height: 360px;
  overflow: auto;
}

.chart-img {
  max-width: 100%;
  max-height: 340px;
  object-fit: contain;
  border-radius: var(--r-xs);
}

.sample-badge-banner {
  padding: var(--s6) var(--s4);
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.sbb-title {
  font-family: var(--font-serif);
  font-size: var(--t-lead);
  color: var(--ink);
}
.sbb-ref {
  font-size: var(--t-tiny);
  color: var(--cat-2);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}

/* ---- parameter form ---------------------------------------------------- */

.mini-btn {
  font-size: var(--t-micro);
  font-weight: 600;
  color: var(--ink-dim);
  background: var(--void-lift);
  border: 1px solid var(--rule);
  border-radius: var(--r-xs);
  padding: 3px 8px;
  cursor: pointer;
  white-space: nowrap;
}
.mini-btn:hover:not(:disabled) {
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
}
.mini-btn:disabled {
  opacity: 0.5;
  cursor: progress;
}

.input-label {
  display: block;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  color: var(--ink-dim);
  margin-bottom: 5px;
  text-transform: uppercase;
}

.form-row-3 {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
}
.field-block {
  min-width: 0;
}

.field-input,
.field-select {
  width: 100%;
  background: var(--void-lift);
  border: 1px solid var(--rule-hi);
  color: var(--ink);
  font-size: var(--t-tiny);
  padding: 6px 9px;
  border-radius: var(--r-xs);
}
.field-input::placeholder {
  color: var(--ink-dim);
}
.field-input:focus,
.field-select:focus {
  outline: none;
  border-color: var(--phosphor);
}
.field-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  border-style: dashed;
}
.field-select option:disabled {
  color: var(--ink-dim);
}

.cap-note {
  margin: var(--s2) 0 0;
  font-size: var(--t-micro);
  line-height: 1.55;
  color: var(--ink-dim);
  max-width: 88ch;
}
.cap-note.is-warn {
  color: var(--warn);
}
.cap-off {
  color: var(--ink-dim);
}
.cap-reason {
  color: var(--ink-dim);
}

/* ---- bars-served proof panel ------------------------------------------ */

.bars-meta-panel {
  margin-top: var(--s3);
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s3);
}
.bmp-head {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-dim);
  margin-bottom: var(--s2);
}
.bmp-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2) var(--s3);
  margin: 0;
}
.bmp-cell {
  min-width: 0;
}
.bmp-cell dt {
  margin: 0;
}
.bmp-cell dd {
  margin: 2px 0 0;
  font-size: var(--t-tiny);
  font-weight: 600;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bmp-wide {
  grid-column: 1 / -1;
}
.bmp-cell dd.src {
  font-weight: 400;
  color: var(--ink-dim);
}
.bmp-note,
.bmp-empty {
  margin: var(--s2) 0 0;
  font-size: var(--t-micro);
  line-height: 1.6;
  color: var(--ink-dim);
  max-width: 84ch;
}
.bmp-note {
  color: var(--warn);
}
.bmp-empty code,
.bmp-note code,
.cap-note code,
.empty-note code,
.basis-missing code,
.ref-empty code {
  font-family: var(--font-data);
  font-size: 0.94em;
  color: var(--ink-dim);
}

.scan-receipt {
  margin: 0 auto 0 0;
  font-size: var(--t-micro);
  color: var(--ink-dim);
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  max-width: 52ch;
}
.scan-same {
  color: var(--ink-dim);
}
.scan-moved {
  color: var(--phosphor);
}

.run-row {
  margin-top: var(--s3);
  display: flex;
  align-items: center;
  gap: var(--s3);
  justify-content: flex-end;
}

.run-btn {
  background: var(--phosphor);
  color: var(--void);
  font-size: var(--t-tiny);
  font-weight: 650;
  padding: 8px 18px;
  border-radius: var(--r-sm);
  cursor: pointer;
  border: none;
}
.run-btn:hover:not(:disabled) {
  background: var(--phosphor-dim);
}
.run-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ---- reference library ------------------------------------------------- */

.reference-card {
  border-color: var(--cat-2);
  background: var(--panel);
}
.ref-badge {
  background: transparent;
  color: var(--cat-2);
  border: 1px solid var(--cat-2);
}
.ref-preamble {
  margin: 0 0 var(--s3);
  font-size: var(--t-micro);
  line-height: 1.65;
  color: var(--ink-faint);
  max-width: 62ch;
}
.ref-preamble em {
  color: var(--cat-2);
  font-style: italic;
}

.reference-list {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.reference-item {
  display: flex;
  gap: var(--s3);
  text-align: left;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}
.reference-item:hover {
  border-color: var(--cat-2);
}
.reference-item.active {
  border-color: var(--cat-2);
  background: var(--panel-raise);
}
.ri-spine {
  width: 3px;
  flex: none;
  background: var(--cat-2);
  opacity: 0.7;
}
.ri-body {
  display: block;
  padding: var(--s2) var(--s3) 10px 0;
  min-width: 0;
}
.ri-top {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
}
.ri-symbol {
  font-size: var(--t-tiny);
  font-weight: 700;
  color: var(--ink);
  letter-spacing: 0.04em;
}
.ri-tf {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}
.ri-title {
  display: block;
  font-family: var(--font-serif);
  font-size: var(--t-small);
  line-height: 1.4;
  color: var(--ink-soft);
  margin-top: 3px;
}
.ri-cite {
  display: block;
  margin-top: 4px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--cat-2);
}
.ri-desc {
  display: block;
  margin-top: 6px;
  font-size: var(--t-micro);
  line-height: 1.6;
  color: var(--ink-dim);
  max-width: 56ch;
}
.ref-empty {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  margin: 0;
}

/* ---- results: provenance ---------------------------------------------- */

.vpa-card.is-reference {
  border-color: var(--cat-2);
}

.provenance-strip {
  display: flex;
  gap: var(--s3);
  align-items: flex-start;
  padding: var(--s3);
  margin-bottom: var(--s3);
  border-radius: var(--r-md);
  border: 1px solid var(--cat-2);
  background: var(--void);
}
.prov-mark {
  width: 30px;
  height: 30px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--r-sm);
  background: var(--void-lift);
  color: var(--cat-2);
  border: 1px solid var(--cat-2);
}
.prov-title {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--cat-2);
}
.prov-sub {
  font-family: var(--font-serif);
  font-size: var(--t-body);
  line-height: 1.4;
  color: var(--ink);
  margin-top: 3px;
}
.prov-cite {
  display: inline-block;
  margin-left: var(--s2);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--cat-2);
  vertical-align: middle;
}
.prov-desc {
  margin: 6px 0 0;
  font-size: var(--t-tiny);
  line-height: 1.6;
  color: var(--ink-dim);
  max-width: 82ch;
}

/* ---- hero -------------------------------------------------------------- */

.hero-summary-strip {
  display: grid;
  /* Four metrics across on the desk, wrapping instead of crushing below 1200px —
     same auto-fit convention the VAP strip in this file already uses. */
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--s3);
  background: var(--void);
  padding: var(--s3) var(--s4);
  border-radius: var(--r-md);
  border: 1px solid var(--rule);
  margin-bottom: var(--s4);
}

.metric-col {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.metric-label {
  margin-bottom: 4px;
}
.metric-val {
  font-size: var(--t-body);
  font-weight: 650;
  line-height: 1.25;
  color: var(--ink);
  letter-spacing: var(--track-tight);
}

/* ---- VPA Clean Read panel ---------------------------------------------- */

.vpa-clean-read-card {
  container-type: inline-size;
  container-name: vpa-read;
  margin-bottom: var(--s4);
  padding: var(--s3) var(--s4);
  background: var(--panel-raise);
  border: 1px solid var(--rule);
  border-left: 1px solid var(--phosphor);
  border-radius: var(--r-md);
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.cr-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--s2) var(--s3);
}

.cr-badge {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.cr-stance {
  display: inline-block;
  padding: 3px 8px;
  border-radius: var(--r-xs);
  font-family: var(--font-data);
  font-weight: 700;
  font-size: var(--t-tiny);
  letter-spacing: var(--track-label);
  text-transform: uppercase;
}

.cr-tone-pos .cr-stance {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}

.cr-tone-neg .cr-stance {
  background: var(--short-wash);
  color: var(--short);
  border: 1px solid var(--short);
}

.cr-tone-warn .cr-stance {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}

.cr-headline {
  font-weight: 600;
  font-size: var(--t-body);
  color: var(--ink);
}

.cr-meta {
  display: flex;
  align-items: center;
  gap: var(--s2);
  font-size: var(--t-small);
}

.cr-meta-item.pos {
  color: var(--call-hi);
}

.cr-meta-item.neg {
  color: var(--short);
}

.cr-meta-item.warn {
  color: var(--warn);
}

.cr-meta-item.flat {
  color: var(--ink-dim);
}

.cr-sep {
  color: var(--ink-dim);
}

.cr-executive-prose {
  margin: 0;
  font-size: var(--t-small);
  line-height: 1.5;
  color: var(--ink-soft);
  max-width: 90ch;
}

.cr-blueprint-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border-top: 1px solid var(--rule);
}

.cr-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 12px 16px 14px 0;
  border-bottom: 1px solid var(--rule);
}

.cr-cell:nth-child(odd) {
  padding-right: 20px;
  border-right: 1px solid var(--rule);
}

.cr-cell:nth-child(even) {
  padding-left: 20px;
}

.cr-cell-val {
  font-size: var(--t-small);
  color: var(--ink-soft);
  line-height: 1.45;
  max-width: 52ch;
  overflow-wrap: break-word;
}

.cr-cell-val.pos {
  color: var(--call-hi);
}

.cr-cell-val.neg {
  color: var(--short);
}

.cr-cell-val.warn {
  color: var(--warn);
}

.cr-levels-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s3) var(--s4);
  align-items: start;
  padding-top: var(--s2);
}

.cr-lvl-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}

.cr-lvl-item b {
  color: var(--ink);
}

.cr-lvl-item b.pos {
  color: var(--call-hi);
}

.cr-lvl-item b.neg {
  color: var(--short);
}

.cr-lvl-item b.warn {
  color: var(--warn);
}

.cr-signals-item {
  grid-column: 1 / -1;
  margin-left: 0;
  padding-top: var(--s1);
  border-top: 1px solid var(--rule);
}

.cr-sig-tags {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.cr-sig-chip {
  display: inline-block;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-size: var(--t-micro);
  font-weight: 500;
}

.cr-sig-chip.pos {
  background: var(--call-wash);
  color: var(--call-hi);
}

.cr-sig-chip.neg {
  background: var(--short-wash);
  color: var(--short);
}

.cr-sig-chip.flat {
  background: var(--panel-raise);
  color: var(--ink-dim);
}
.cr-sig-chip {
  cursor: pointer;
  border: 1px solid transparent;
}
.cr-sig-chip:hover {
  border-color: var(--rule-hi);
}

.risk-ladder {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 4px 0 2px;
  width: fit-content;
  max-width: 100%;
}
.rl-head,
.rl-foot {
  width: 100%;
}
.rl-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s3);
}
.rl-span {
  font-size: var(--t-micro);
  color: var(--ink-faint);
}
.rl-rungs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0;
}
.rl-rung {
  display: grid;
  grid-template-columns: 7.25rem 0.75rem 6.75rem 4.5rem;
  align-items: center;
  column-gap: 10px;
  min-height: 36px;
  position: relative;
  padding-inline: 8px;
}
.rl-roles {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ink-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rl-tick {
  position: relative;
  justify-self: center;
  align-self: stretch;
  width: 11px;
  color: var(--rule-hi);
  z-index: 1;
}
.rl-tick::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  height: 1px;
  background: currentColor;
  transform: translateY(-50%);
  z-index: 1;
}
.rl-rung.is-entry .rl-tick {
  width: 13px;
  color: var(--phosphor);
}
.rl-rung.is-entry .rl-tick::after {
  height: 2px;
}
.rl-seg {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 1px;
  height: 100%;
  transform: translateX(-50%);
  pointer-events: none;
}
.rl-seg.seg-risk {
  background: var(--short);
}
.rl-seg.seg-reward {
  background: var(--long);
}
.rl-seg.seg-idle {
  background: var(--rule-hi);
}
.rl-px {
  font-size: var(--t-small);
  font-weight: 650;
  color: var(--ink);
  letter-spacing: var(--track-tight);
}
.rl-delta {
  justify-self: end;
  font-size: var(--t-micro);
  color: var(--ink-faint);
}
.rl-rung.tone-stop .rl-roles,
.rl-rung.tone-stop .rl-px,
.rl-rung.tone-stop .rl-delta,
.rl-rung.tone-stop .rl-tick {
  color: var(--short);
}
.rl-rung.tone-target .rl-roles,
.rl-rung.tone-target .rl-px,
.rl-rung.tone-target .rl-delta,
.rl-rung.tone-target .rl-tick {
  color: var(--long);
}
.rl-rung.tone-entry .rl-roles,
.rl-rung.tone-entry .rl-px,
.rl-rung.tone-entry .rl-tick {
  color: var(--phosphor);
}
.rl-rung.tone-last .rl-roles,
.rl-rung.tone-last .rl-px {
  color: var(--ink-soft);
}
.rl-rung.is-entry {
  background: var(--phosphor-wash);
  box-shadow:
    inset 0 1px 0 var(--rule),
    inset 0 -1px 0 var(--rule);
}
.rl-foot {
  display: flex;
  gap: var(--s2);
  font-size: var(--t-micro);
  color: var(--ink-dim);
  padding-top: 4px;
}
.rl-risk {
  color: var(--short);
}
.rl-reward {
  color: var(--long);
}
.exec-rail {
  margin-bottom: var(--s4);
}

.sr-ladder {
  list-style: none;
  margin: 0 0 var(--s3);
  padding: 0;
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  overflow: hidden;
}
.sr-spot,
.sr-rung {
  display: grid;
  grid-template-columns: 88px 88px 72px 48px minmax(0, 1fr);
  gap: var(--s2);
  align-items: center;
  padding: 7px 12px;
  border-bottom: 1px solid var(--rule);
}
.sr-spot {
  background: var(--void);
}
.sr-rung {
  cursor: crosshair;
}
.sr-rung:last-child {
  border-bottom: none;
}
.sr-rung.hot {
  background: var(--panel-hi);
}
.sr-rung.support .sr-px {
  color: var(--long);
}
.sr-rung.resistance .sr-px {
  color: var(--short);
}
.sr-kind {
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ink-dim);
}
.sr-dist,
.sr-touch {
  color: var(--ink-faint);
  font-size: var(--t-micro);
}

.prose-sr .legacy-head {
  margin-bottom: var(--s2);
}
.evidence-row {
  cursor: pointer;
}
.evidence-row.selected {
  outline: 1px solid var(--phosphor-dim);
  background: var(--phosphor-wash);
}
.ev-locus {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: 4px;
  color: var(--ink-dim);
  font-size: var(--t-micro);
}
.ev-px {
  color: var(--ink-soft);
}
.sw-ent {
  background: var(--phosphor-wash);
  border-top: 1.5px solid var(--phosphor);
}

@media (max-width: 600px) {
  .cr-top {
    flex-direction: column;
    align-items: flex-start;
  }
  .cr-blueprint-grid {
    grid-template-columns: 1fr;
  }
  .cr-cell:nth-child(odd),
  .cr-cell:nth-child(even) {
    padding-left: 0;
    padding-right: 0;
    border-right: none;
  }
  .cr-signals-item {
    margin-left: 0;
  }
}

@container vpa-read (max-width: 560px) {
  .cr-blueprint-grid {
    grid-template-columns: 1fr;
  }
  .cr-cell:nth-child(odd),
  .cr-cell:nth-child(even) {
    padding-left: 0;
    padding-right: 0;
    border-right: none;
  }
  .cr-levels-strip {
    grid-template-columns: 1fr 1fr;
  }
  .rl-rung {
    grid-template-columns: 5.5rem 0.75rem 6.25rem 3.75rem;
  }
}

/* ---- tabs -------------------------------------------------------------- */

.vpa-tabs {
  display: flex;
  gap: var(--s1);
  border-bottom: 1px solid var(--rule);
  margin-bottom: var(--s4);
}

.tab-btn {
  font-size: var(--t-tiny);
  font-weight: 600;
  padding: 8px 13px;
  color: var(--ink-dim);
  border-bottom: 2px solid transparent;
  cursor: pointer;
  background: transparent;
  border-top: none;
  border-left: none;
  border-right: none;
  white-space: nowrap;
}
.tab-btn:hover {
  color: var(--ink);
}
.tab-btn.active {
  color: var(--phosphor);
  border-bottom-color: var(--phosphor);
}

/* ---- forensic sections ------------------------------------------------- */

.forensic-section,
.evidence-section {
  margin-bottom: var(--s4);
}

.section-title {
  font-size: var(--t-tiny);
  font-weight: 650;
  letter-spacing: var(--track-tight);
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 var(--s2);
}
.section-title :deep(svg) {
  color: var(--ink-dim);
}
.title-count,
.title-sub {
  font-size: var(--t-micro);
  font-weight: 500;
  color: var(--ink-dim);
  letter-spacing: 0;
}
.title-sub {
  font-style: italic;
}

.prose-panel {
  font-size: var(--t-tiny);
  line-height: 1.7;
  color: var(--ink-soft);
  background: var(--void);
  padding: var(--s3);
  border-radius: var(--r-sm);
  border: 1px solid var(--rule);
  margin: 0;
  max-width: 96ch;
}

.table-frame {
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  /* Wide tables (7-column levels) must scroll, not clip, on narrow columns. */
  overflow-x: auto;
}

.vpa-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-tiny);
  text-align: left;
}
.vpa-table th {
  background: var(--panel-raise);
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  padding: 7px 10px;
  border-bottom: 1px solid var(--rule-hi);
  white-space: nowrap;
}
.vpa-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--rule);
  background: var(--void-lift);
  color: var(--ink-soft);
  vertical-align: top;
}
.vpa-table tbody tr:last-child td {
  border-bottom: none;
}
.vpa-table th.num,
.vpa-table td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.td-name {
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}
.td-strong {
  font-weight: 650;
  color: var(--ink);
}
.td-dim {
  color: var(--ink-dim);
}
.td-prose {
  color: var(--ink-soft);
  line-height: 1.6;
  min-width: 22ch;
}
.td-empty {
  color: var(--ink-dim);
  font-style: italic;
  text-align: center;
}

.status-chip {
  display: inline-block;
  font-size: var(--t-micro);
  font-weight: 650;
  letter-spacing: 0.02em;
  padding: 2px 6px;
  border-radius: var(--r-xs);
  white-space: nowrap;
}
.chip-pos {
  background: var(--call-wash);
  color: var(--call-hi);
  border: 1px solid var(--call-dim);
}
.chip-warn {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}
.chip-neutral {
  background: var(--panel-raise);
  color: var(--ink-dim);
  border: 1px solid var(--rule);
}

.grid-2-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
  margin-bottom: var(--s4);
}

.sub-panel {
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s3);
  min-width: 0;
}
.sub-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s2);
}
.sp-body {
  margin-top: var(--s2);
}
.sp-headline {
  font-size: var(--t-tiny);
  font-weight: 650;
  color: var(--phosphor);
  letter-spacing: var(--track-tight);
}
.sp-detail {
  margin: 5px 0 0;
  font-size: var(--t-micro);
  line-height: 1.65;
  color: var(--ink-dim);
  max-width: 54ch;
}

/* ---- Ch.8 dynamic trend & Ch.11 congestion ----------------------------- */

.struct-figs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s2);
  padding-bottom: var(--s2);
  margin-bottom: var(--s2);
  border-bottom: 1px solid var(--rule);
}
.struct-fig {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
/* These panels sit in a narrow two-up grid; a wrapped label beats an
   ellipsised one, which turned both slope rows into an identical "SLOPE…". */
.struct-fig .label,
.sub-panel-header .label {
  white-space: normal;
  overflow: visible;
  line-height: 1.3;
}
.struct-val {
  font-size: var(--t-small);
  font-weight: 650;
  color: var(--ink);
}
.struct-cite {
  margin-top: 5px;
  font-size: var(--t-micro);
  color: var(--ink-faint);
  font-style: italic;
}

.congestion-list {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.congestion-row {
  border-left: 1px solid var(--rule-hi);
  padding-left: var(--s2);
}
.congestion-row.pos {
  border-left-color: var(--call-hi);
}
.congestion-row.neg {
  border-left-color: var(--put-hi);
}
.cg-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--s2);
}
.cg-dir {
  color: var(--ink-faint);
}
.cg-level {
  margin-left: auto;
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

/* ---- numeric trade levels behind the risk:reward ----------------------- */

.level-triplet {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
  margin-top: var(--s3);
  padding: var(--s3);
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
}
.lt-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.lt-val {
  font-size: var(--t-small);
  font-weight: 650;
  color: var(--ink);
}
.lt-sub {
  font-size: var(--t-micro);
  color: var(--ink-faint);
}

/* ---- read quality (confidence decomposition) --------------------------- */

.quality-panel {
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s3);
}
.quality-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  padding-bottom: var(--s2);
  margin-bottom: var(--s3);
  border-bottom: 1px solid var(--rule);
}
.quality-score {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.quality-fig {
  font-size: var(--t-display);
  font-weight: 650;
  line-height: 1;
}
.quality-reads {
  display: flex;
  gap: var(--s4);
}
.quality-read {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: right;
}
.quality-read b {
  font-size: var(--t-small);
  color: var(--ink);
}

.quality-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.quality-row {
  display: grid;
  grid-template-columns: minmax(9ch, 18ch) 1fr 5ch;
  align-items: center;
  gap: var(--s2);
}
.quality-label {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  line-height: 1.3;
}
.quality-track {
  position: relative;
  height: 5px;
  border-radius: 3px;
  background: var(--panel-raise);
  overflow: hidden;
}
.quality-fill {
  display: block;
  height: 100%;
  background: var(--phosphor);
  border-radius: 3px;
}
.quality-fill.weak {
  background: var(--warn);
}
.quality-num {
  font-size: var(--t-micro);
  color: var(--ink-soft);
  text-align: right;
}
.quality-method {
  margin: var(--s3) 0 0;
  font-size: var(--t-micro);
  color: var(--ink-faint);
  font-style: italic;
  max-width: 72ch;
}

.thresholds-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: var(--s2);
  padding: var(--s2) var(--s3);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  background: var(--panel-raise);
}
.thresholds-src {
  font-size: var(--t-micro);
  color: var(--ink-dim);
}
.thresholds-note {
  font-size: var(--t-micro);
  color: var(--ink-faint);
  max-width: 64ch;
}

/* ---- levels ------------------------------------------------------------ */

.vap-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s3);
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s3);
  margin-bottom: var(--s2);
}
.vap-cell {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.vap-val {
  margin-top: 3px;
  font-size: var(--t-small);
  font-weight: 650;
  color: var(--ink);
}
.vap-sub {
  margin-top: 2px;
  font-size: var(--t-micro);
  color: var(--ink-faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.levels-table .level-row {
  cursor: crosshair;
  transition: background 0.12s ease;
}
.levels-table .level-row:hover td,
.levels-table .level-row.hot td {
  background: var(--panel-raise);
}
.lvl-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 2px;
  margin-right: 6px;
  background: var(--ink-ghost);
}
.level-row.support .lvl-dot {
  background: var(--long);
}
.level-row.resistance .lvl-dot {
  background: var(--short);
}
.rr-tag {
  display: inline-block;
  margin-left: 6px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--warn);
  border-bottom: 1px dashed var(--warn);
  cursor: help;
}

.strength-cell {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  min-width: 76px;
}
.strength-fill {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  height: 4px;
  border-radius: 2px;
  background: var(--phosphor);
  opacity: 0.45;
  max-width: 46px;
}
.strength-num {
  font-weight: 600;
  color: var(--ink);
}

.empty-note {
  margin: 0;
  padding: var(--s3);
  font-size: var(--t-micro);
  line-height: 1.7;
  color: var(--ink-soft);
  background: var(--void);
  border: 1px dashed var(--rule-hi);
  border-radius: var(--r-md);
  max-width: 92ch;
}

.legacy-sr {
  margin-top: var(--s2);
  font-size: var(--t-micro);
}
.legacy-sr summary {
  cursor: pointer;
  color: var(--ink-dim);
  font-weight: 600;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  padding: 4px 0;
}
.legacy-sr summary:hover {
  color: var(--ink-soft);
}
.legacy-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s2) var(--s3);
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  padding: var(--s3);
  margin-top: 4px;
}
.legacy-wide {
  grid-column: 1 / -1;
}
.legacy-val {
  display: block;
  margin-top: 3px;
  font-size: var(--t-tiny);
  color: var(--ink-soft);
  line-height: 1.5;
}

/* ---- scenarios --------------------------------------------------------- */

.scenario-card {
  background: var(--void);
  border-radius: var(--r-md);
  padding: var(--s3) var(--s4);
  border: 1px solid var(--rule);
}
.scenario-card.primary {
  border-color: var(--phosphor-dim);
}
.scenario-card.alternative {
  margin-top: var(--s2);
  border-color: var(--rule-hi);
}

.scenario-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--s3);
}
.sh-left {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
  min-width: 0;
}
.sh-move {
  font-size: var(--t-small);
  font-weight: 650;
  color: var(--ink);
  letter-spacing: var(--track-tight);
}

.badge-primary,
.badge-alt {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: var(--r-xs);
  white-space: nowrap;
}
.badge-primary {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border: 1px solid var(--phosphor-dim);
}
.badge-alt {
  background: var(--warn-wash);
  color: var(--warn);
  border: 1px solid var(--warn);
}

.prob-block {
  text-align: right;
  flex: none;
}
.prob-figure {
  font-size: var(--t-fig);
  font-weight: 650;
  line-height: 1.05;
  color: var(--phosphor);
}
.prob-figure.alt {
  font-size: var(--t-lead);
  color: var(--warn);
}
.prob-caption {
  margin-top: 2px;
  color: var(--ink-dim);
}

.basis-strip {
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
}
.basis-scores {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s4);
}
.basis-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.basis-item b {
  font-size: var(--t-tiny);
  font-weight: 650;
}
.basis-note {
  margin: var(--s2) 0 0;
  padding-top: var(--s2);
  border-top: 1px solid var(--rule);
  font-size: var(--t-micro);
  line-height: 1.6;
  color: var(--ink-dim);
  font-style: italic;
  max-width: 78ch;
}
.basis-validation {
  display: flex;
  gap: var(--s1);
  align-items: flex-start;
  margin: var(--s2) 0 0;
  padding: var(--s2);
  border: 1px solid var(--warn);
  border-radius: 3px;
  background: color-mix(in srgb, var(--warn) 7%, transparent);
  font-size: var(--t-micro);
  line-height: 1.6;
  color: var(--ink);
  max-width: 78ch;
}

.basis-validation b {
  color: var(--warn);
}

.basis-missing {
  margin: var(--s3) 0 0;
  padding: var(--s2) var(--s3);
  font-size: var(--t-micro);
  line-height: 1.65;
  color: var(--warn);
  background: var(--warn-wash);
  border: 1px dashed var(--warn);
  border-radius: var(--r-sm);
  max-width: 92ch;
}

.primary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
  margin-top: var(--s3);
  padding: var(--s2) var(--s3);
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
}
.pg-val {
  display: block;
  margin-top: 3px;
  font-size: var(--t-tiny);
  font-weight: 600;
  color: var(--ink);
}

.rationale {
  margin-top: var(--s3);
}
.rationale p {
  margin: 5px 0 0;
  font-size: var(--t-tiny);
  line-height: 1.7;
  color: var(--ink-soft);
  max-width: 84ch;
}

/* ---- evidence ledger --------------------------------------------------- */

.evidence-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  overflow: hidden;
}

.evidence-row {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr) 108px;
  gap: var(--s3);
  align-items: start;
  padding: 10px var(--s3);
  background: var(--void-lift);
  border-bottom: 1px solid var(--rule);
}
.evidence-row:last-child {
  border-bottom: none;
}

.ev-dir {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 1px;
}
.ev-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
  background: var(--ink-ghost);
}
.evidence-row.pos .ev-dot {
  background: var(--long);
}
.evidence-row.neg .ev-dot {
  background: var(--short);
}
.ev-dir-text {
  color: var(--ink-dim);
}
.evidence-row.pos .ev-dir-text {
  color: var(--long);
}
.evidence-row.neg .ev-dir-text {
  color: var(--short);
}

.ev-main {
  min-width: 0;
}
.ev-head {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  flex-wrap: wrap;
}
.ev-signal {
  font-size: var(--t-tiny);
  font-weight: 650;
  color: var(--ink);
  text-transform: capitalize;
  letter-spacing: var(--track-tight);
}
.ev-cite {
  font-family: var(--font-serif);
  font-size: var(--t-micro);
  color: var(--cat-2);
  border-bottom: 1px dotted var(--cat-2);
}
.ev-detail {
  margin: 4px 0 0;
  font-size: var(--t-micro);
  line-height: 1.65;
  color: var(--ink-dim);
  max-width: 74ch;
}
.ev-bars {
  margin-top: 4px;
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.ev-weight {
  display: flex;
  align-items: center;
  gap: var(--s2);
  justify-content: flex-end;
  padding-top: 2px;
}
.ev-weight-track {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: var(--rule);
  overflow: hidden;
}
.ev-weight-fill {
  display: block;
  height: 100%;
  background: var(--ink-ghost);
}
.evidence-row.pos .ev-weight-fill {
  background: var(--long);
}
.evidence-row.neg .ev-weight-fill {
  background: var(--short);
}
.ev-weight-num {
  font-size: var(--t-micro);
  font-weight: 650;
  color: var(--ink);
  min-width: 4ch;
  text-align: right;
}

/* ---- alternatives ------------------------------------------------------ */

.alt-block {
  margin-top: var(--s4);
}
.alt-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2) var(--s3);
  margin-bottom: var(--s2);
}
.alt-head h4 {
  margin: 0;
  /* The label base style ellipsises; this heading is a sentence, so let it wrap. */
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
}
.alt-caution {
  font-family: var(--font-data);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: var(--track-label);
  color: var(--warn);
  white-space: nowrap;
}
.alt-sumwarn {
  margin: 0 0 var(--s2);
  font-size: var(--t-micro);
  color: var(--warn);
}
.alt-read {
  margin: var(--s2) 0 0;
  font-size: var(--t-tiny);
  line-height: 1.7;
  color: var(--ink-soft);
  max-width: 84ch;
}
.alt-risk {
  margin: var(--s2) 0 0;
  font-size: var(--t-micro);
  line-height: 1.6;
  color: var(--warn);
  font-style: italic;
  max-width: 78ch;
}

.invalidation-box {
  background: var(--short-wash);
  border: 1px solid var(--short);
  border-radius: var(--r-sm);
  padding: var(--s2) var(--s3);
  margin-top: var(--s3);
}
.inv-title {
  font-size: var(--t-micro);
  font-weight: 700;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--short);
}
.inv-val {
  margin-top: 4px;
  font-size: var(--t-tiny);
  line-height: 1.6;
  color: var(--ink);
}

/* ---- execution --------------------------------------------------------- */

.execution-card {
  background: var(--void);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s4);
}

.exec-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
  padding-bottom: var(--s3);
  border-bottom: 1px solid var(--rule);
}
.exec-col {
  display: flex;
  flex-direction: column;
}
.exec-val {
  font-size: var(--t-fig);
  font-weight: 650;
  line-height: 1.15;
  margin-top: 3px;
  letter-spacing: var(--track-tight);
  color: var(--ink);
}
.exec-hint {
  margin-top: 2px;
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.exec-details {
  margin-top: var(--s4);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}
.exec-detail-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.detail-val {
  font-size: var(--t-tiny);
  line-height: 1.6;
  color: var(--ink);
  max-width: 86ch;
}

.rules-block {
  margin-top: var(--s4);
  padding-top: var(--s3);
  border-top: 1px solid var(--rule);
}
.rules-list {
  list-style-type: disc;
  padding-left: 18px;
  margin: var(--s2) 0 0;
  font-size: var(--t-tiny);
  line-height: 1.75;
  color: var(--ink-dim);
  max-width: 88ch;
}

/* ---- empty state ------------------------------------------------------- */

.empty-state {
  background: var(--panel);
  border: 1px solid var(--rule);
  border-radius: var(--r-lg);
  padding: var(--s7) var(--s4);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.es-icon {
  color: var(--ink-dim);
}
.es-title {
  font-size: var(--t-body);
  font-weight: 600;
  color: var(--ink);
  margin: var(--s3) 0 0;
  letter-spacing: var(--track-tight);
}
.es-body {
  margin: 6px 0 0;
  font-size: var(--t-tiny);
  line-height: 1.6;
  color: var(--ink-dim);
  max-width: 52ch;
}

/* ---- codex drawer ------------------------------------------------------ */

.codex-drawer-backdrop {
  position: fixed;
  inset: 0;
  background: var(--panel-wash);
  /* Scrim veil only — no backdrop blur (glass piles). */
  z-index: 999;
  display: flex;
  justify-content: flex-end;
}

.codex-drawer {
  width: 520px;
  max-width: 90vw;
  height: 100%;
  background: var(--panel);
  border-left: 1px solid var(--rule-hi);
  display: flex;
  flex-direction: column;
}

.drawer-header {
  padding: var(--s4) var(--s5);
  border-bottom: 1px solid var(--rule);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s3);
}
.drawer-title {
  font-family: var(--font-display);
  font-size: var(--t-lead);
  font-weight: 650;
  letter-spacing: var(--track-display);
  color: var(--ink);
  margin: 0;
}
.drawer-sub {
  margin: 3px 0 0;
  font-size: var(--t-micro);
  color: var(--ink-dim);
}

.close-drawer-btn {
  color: var(--ink-dim);
  font-size: var(--t-lead);
  line-height: 1;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px;
}
.close-drawer-btn:hover {
  color: var(--ink);
}

.drawer-body {
  padding: var(--s5);
  overflow-y: auto;
  flex: 1;
}

.codex-section + .codex-section {
  margin-top: var(--s5);
}
.codex-sec-title {
  font-family: var(--font-data);
  font-size: var(--t-tiny);
  font-weight: 650;
  text-transform: uppercase;
  color: var(--phosphor);
  letter-spacing: var(--track-label);
  margin: 0 0 var(--s2);
}
.codex-stack {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}
.codex-card {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--s3);
}
.cc-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--s2);
}
.cc-title {
  font-size: var(--t-tiny);
  font-weight: 650;
  color: var(--phosphor);
  letter-spacing: var(--track-tight);
}
.cc-title.ink {
  color: var(--ink);
}
.cc-cat {
  color: var(--ink-dim);
}
.cc-body {
  margin-top: 5px;
  font-size: var(--t-micro);
  line-height: 1.7;
  color: var(--ink-soft);
  max-width: 64ch;
}
.cc-app {
  margin-top: 6px;
  font-family: var(--font-data);
  font-size: var(--t-micro);
  line-height: 1.6;
  color: var(--ink-dim);
}
.cc-scenarios {
  margin: var(--s2) 0 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.cc-scenarios > div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: var(--s2);
  font-size: var(--t-micro);
  line-height: 1.6;
}
.cc-scenarios dt {
  color: var(--ink-dim);
  font-weight: 600;
}
.cc-scenarios dd {
  margin: 0;
  color: var(--ink-dim);
}

/* ---- spinner ----------------------------------------------------------- */

.spinner {
  width: 13px;
  height: 13px;
  border: 2px solid var(--ink-dim);
  border-radius: 50%;
  border-top-color: var(--ink);
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner {
    animation-duration: 2.4s;
  }
}
</style>
