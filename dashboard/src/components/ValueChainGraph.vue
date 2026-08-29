<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SupplyChainEdge, SupplyChainNode, SupplyTier } from '@/api'
import {
  elasticityTone,
  tierBadgeLabel,
  tierColorClass,
  formatMarketCap,
  flowTypeClass,
  flowMarkerId,
  relationshipLabel,
} from '@/chainDisplay'

const props = defineProps<{
  nodes: SupplyChainNode[]
  edges: SupplyChainEdge[]
  selectedSymbol?: string | null
}>()

const emit = defineEmits<{
  (e: 'select-node', symbol: string): void
}>()

const hoveredSymbol = ref<string | null>(null)
const hoveredEdgeId = ref<string | null>(null)
const tierFilter = ref<string>('all')

function tierToColumn(tier: SupplyTier): number {
  switch (tier) {
    case 'tier2_supplier':
      return 0
    case 'tier1_supplier':
      return 1
    case 'mega_driver':
      return 2
    case 'horizontal_enabler':
      return 2
    case 'downstream_customer':
      return 3
    default:
      return 1
  }
}

const columnLabels = [
  'Tier 2: Materials & Metrology',
  'Tier 1: Optics, Memory, Cooling',
  'Core Driver & Infrastructure',
  'Downstream Cloud & Enterprise',
]

interface LayoutNode extends SupplyChainNode {
  col: number
  row: number
  x: number
  y: number
}

const filteredNodes = computed(() => {
  if (tierFilter.value === 'all') return props.nodes
  if (tierFilter.value === 'tier1') return props.nodes.filter((n) => n.tier === 'tier1_supplier')
  if (tierFilter.value === 'tier2') return props.nodes.filter((n) => n.tier === 'tier2_supplier')
  if (tierFilter.value === 'driver')
    return props.nodes.filter((n) => n.tier === 'mega_driver' || n.tier === 'horizontal_enabler')
  if (tierFilter.value === 'customer')
    return props.nodes.filter((n) => n.tier === 'downstream_customer')
  return props.nodes
})

const layoutNodes = computed((): LayoutNode[] => {
  const cols: SupplyChainNode[][] = [[], [], [], []]
  for (const n of filteredNodes.value) {
    const colIdx = tierToColumn(n.tier)
    cols[colIdx].push(n)
  }

  const maxRows = Math.max(...cols.map((c) => c.length), 3)
  const result: LayoutNode[] = []
  const colWidth = 240
  const startX = 60
  const cardHeight = 72
  const gapY = 16

  cols.forEach((colNodes, colIdx) => {
    // Balanced vertical offset if column has fewer rows than the max column
    const colOffsetY = Math.max(0, (maxRows - colNodes.length) * (cardHeight + gapY) * 0.12)
    colNodes.forEach((node, rowIdx) => {
      result.push({
        ...node,
        col: colIdx,
        row: rowIdx,
        x: startX + colIdx * colWidth,
        y: 40 + colOffsetY + rowIdx * (cardHeight + gapY),
      })
    })
  })

  return result
})

const totalHeight = computed(() => {
  const maxRows = Math.max(
    ...[0, 1, 2, 3].map((c) => layoutNodes.value.filter((n) => n.col === c).length),
    5,
  )
  return Math.max(540, 60 + maxRows * (72 + 16) + 40)
})

const nodeMap = computed(() => {
  const map = new Map<string, LayoutNode>()
  for (const n of layoutNodes.value) {
    map.set(n.symbol, n)
  }
  return map
})

interface ComputedEdge extends SupplyChainEdge {
  d: string
  active: boolean
  flowType: 'flow-supply' | 'flow-demand' | 'flow-partner' | 'flow-peer'
  markerUrl: string
  midX: number
  midY: number
}

const computedEdges = computed((): ComputedEdge[] => {
  // Precompute incident edge counts for multi-slot distributed anchors
  const srcSlots = new Map<string, string[]>()
  const tgtSlots = new Map<string, string[]>()

  for (const e of props.edges) {
    if (!srcSlots.has(e.source)) srcSlots.set(e.source, [])
    srcSlots.get(e.source)!.push(e.id)

    if (!tgtSlots.has(e.target)) tgtSlots.set(e.target, [])
    tgtSlots.get(e.target)!.push(e.id)
  }

  return props.edges
    .map((e) => {
      const src = nodeMap.value.get(e.source)
      const tgt = nodeMap.value.get(e.target)
      if (!src || !tgt) return null

      const active =
        props.selectedSymbol === e.source ||
        props.selectedSymbol === e.target ||
        hoveredSymbol.value === e.source ||
        hoveredSymbol.value === e.target ||
        hoveredEdgeId.value === e.id

      const flowType = flowTypeClass(e.relationship, src.col, tgt.col)
      const markerUrl = flowMarkerId(flowType, active)

      const cardWidth = 180
      const cardHeight = 72

      // Distributed vertical anchors to prevent colliding clumped lines
      const srcList = srcSlots.get(e.source) ?? []
      const srcIdx = srcList.indexOf(e.id)
      const srcTotal = srcList.length
      const srcSlotY = srcTotal > 1 ? 18 + ((srcIdx + 0.5) / srcTotal) * 36 : cardHeight / 2

      const tgtList = tgtSlots.get(e.target) ?? []
      const tgtIdx = tgtList.indexOf(e.id)
      const tgtTotal = tgtList.length
      const tgtSlotY = tgtTotal > 1 ? 18 + ((tgtIdx + 0.5) / tgtTotal) * 36 : cardHeight / 2

      let x1: number
      let y1 = src.y + srcSlotY
      let x2: number
      let y2 = tgt.y + tgtSlotY
      let cx1: number
      let cy1: number
      let cx2: number
      let cy2: number
      let d: string

      if (src.col < tgt.col) {
        // Left to Right Flow (Tier 2 -> Tier 1 -> Driver -> Downstream)
        x1 = src.x + cardWidth
        x2 = tgt.x - 5
        const dx = (x2 - x1) * 0.45
        cx1 = x1 + dx
        cy1 = y1
        cx2 = x2 - dx
        cy2 = y2
        d = `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`
      } else if (src.col > tgt.col) {
        // Right to Left Flow (Downstream Feedback / Procurement)
        x1 = src.x
        x2 = tgt.x + cardWidth + 5
        const dx = (x1 - x2) * 0.45
        cx1 = x1 - dx
        cy1 = y1
        cx2 = x2 + dx
        cy2 = y2
        d = `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`
      } else {
        // Same Column Lateral / Peer Arc (Arcs into gutter without crossing cards)
        x1 = src.x + cardWidth
        y1 = src.y + (y1 < y2 ? 22 : 50)
        x2 = tgt.x + cardWidth + 5
        y2 = tgt.y + (y1 < y2 ? 50 : 22)
        const rowDiff = Math.abs(tgt.row - src.row)
        const arcDist = 26 + Math.min(36, rowDiff * 12)
        cx1 = x1 + arcDist
        cy1 = y1
        cx2 = x2 + arcDist
        cy2 = y2
        d = `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`
      }

      // Exact midpoint on cubic Bezier at t = 0.5
      const midX = 0.125 * x1 + 0.375 * cx1 + 0.375 * cx2 + 0.125 * x2
      const midY = 0.125 * y1 + 0.375 * cy1 + 0.375 * cy2 + 0.125 * y2

      return {
        ...e,
        d,
        active,
        flowType,
        markerUrl,
        midX,
        midY,
      }
    })
    .filter(Boolean) as ComputedEdge[]
})

const activeFloatingEdge = computed(() => {
  if (hoveredEdgeId.value) {
    return computedEdges.value.find((e) => e.id === hoveredEdgeId.value) ?? null
  }
  if (hoveredSymbol.value) {
    return (
      computedEdges.value.find(
        (e) => e.source === hoveredSymbol.value || e.target === hoveredSymbol.value,
      ) ?? null
    )
  }
  if (props.selectedSymbol) {
    return (
      computedEdges.value.find(
        (e) => e.source === props.selectedSymbol || e.target === props.selectedSymbol,
      ) ?? null
    )
  }
  return null
})

function isNodeConnected(symbol: string): boolean {
  if (!props.selectedSymbol && !hoveredSymbol.value) return false
  const activeSym = hoveredSymbol.value || props.selectedSymbol
  if (symbol === activeSym) return true
  return props.edges.some(
    (e) =>
      (e.source === activeSym && e.target === symbol) ||
      (e.target === activeSym && e.source === symbol),
  )
}
</script>

<template>
  <div class="chain-graph-container" data-test="value-chain-graph">
    <div class="graph-header">
      <div class="column-labels">
        <div v-for="(lbl, idx) in columnLabels" :key="idx" class="col-title">
          <span class="col-idx">0{{ idx + 1 }}</span>
          <span class="col-text">{{ lbl }}</span>
        </div>
      </div>

      <div class="graph-header-controls">
        <div class="relationship-legend">
          <span class="legend-item"><span class="legend-dot supply" /> Supply Flow</span>
          <span class="legend-item"><span class="legend-dot demand" /> Enterprise Demand</span>
          <span class="legend-item"><span class="legend-dot partner" /> Co-Engineered</span>
          <span class="legend-item"><span class="legend-dot peer" /> Peer Benchmark</span>
        </div>

        <div class="graph-tier-filters">
          <button
            type="button"
            class="tier-filter-btn"
            :class="{ active: tierFilter === 'all' }"
            @click="tierFilter = 'all'"
          >
            All ({{ nodes.length }})
          </button>
          <button
            type="button"
            class="tier-filter-btn"
            :class="{ active: tierFilter === 'tier1' }"
            @click="tierFilter = 'tier1'"
          >
            Tier 1
          </button>
          <button
            type="button"
            class="tier-filter-btn"
            :class="{ active: tierFilter === 'driver' }"
            @click="tierFilter = 'driver'"
          >
            Drivers
          </button>
        </div>
      </div>
    </div>

    <div class="graph-scroll-surface">
      <svg
        class="graph-svg"
        :style="{ height: `${totalHeight}px` }"
        :viewBox="`0 0 1020 ${totalHeight}`"
        preserveAspectRatio="xMinYMin meet"
      >
        <defs>
          <linearGradient id="edgeGradDefault" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="var(--rule-hi)" stop-opacity="0.3" />
            <stop offset="100%" stop-color="var(--rule-hi)" stop-opacity="0.6" />
          </linearGradient>
          <linearGradient id="edgeGradSupply" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="var(--phosphor-dim)" stop-opacity="0.8" />
            <stop offset="100%" stop-color="var(--phosphor)" stop-opacity="1" />
          </linearGradient>
          <linearGradient id="edgeGradDemand" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="var(--call-dim)" stop-opacity="0.8" />
            <stop offset="100%" stop-color="var(--call-hi)" stop-opacity="1" />
          </linearGradient>
          <linearGradient id="edgeGradPartner" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="var(--cat-5)" stop-opacity="0.8" />
            <stop offset="100%" stop-color="var(--cat-1)" stop-opacity="1" />
          </linearGradient>
          <linearGradient id="edgeGradPeer" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="var(--rule-hi)" stop-opacity="0.6" />
            <stop offset="100%" stop-color="var(--ink-faint)" stop-opacity="0.85" />
          </linearGradient>

          <!-- Crisp Directional Arrow Markers with Zero Clipping -->
          <marker
            id="arrow-default"
            viewBox="0 0 10 10"
            refX="7"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            markerUnits="userSpaceOnUse"
            orient="auto"
          >
            <path d="M 0 2 L 6 5 L 0 8 z" fill="var(--rule-hi)" />
          </marker>
          <marker
            id="arrow-supply"
            viewBox="0 0 10 10"
            refX="7"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            markerUnits="userSpaceOnUse"
            orient="auto"
          >
            <path d="M 0 1.5 L 7 5 L 0 8.5 z" fill="var(--phosphor)" />
          </marker>
          <marker
            id="arrow-demand"
            viewBox="0 0 10 10"
            refX="7"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            markerUnits="userSpaceOnUse"
            orient="auto"
          >
            <path d="M 0 1.5 L 7 5 L 0 8.5 z" fill="var(--call-hi)" />
          </marker>
          <marker
            id="arrow-partner"
            viewBox="0 0 10 10"
            refX="7"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            markerUnits="userSpaceOnUse"
            orient="auto"
          >
            <path d="M 0 1.5 L 7 5 L 0 8.5 z" fill="var(--cat-1)" />
          </marker>
          <marker
            id="arrow-peer"
            viewBox="0 0 10 10"
            refX="7"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            markerUnits="userSpaceOnUse"
            orient="auto"
          >
            <path d="M 0 2 L 6 5 L 0 8 z" fill="var(--ink-faint)" />
          </marker>
        </defs>

        <!-- Edges -->
        <g class="edges-layer">
          <path
            v-for="e in computedEdges"
            :key="e.id"
            :d="e.d"
            class="chain-edge"
            :class="[e.flowType, { active: e.active }]"
            :stroke="
              e.active
                ? e.flowType === 'flow-supply'
                  ? 'url(#edgeGradSupply)'
                  : e.flowType === 'flow-demand'
                    ? 'url(#edgeGradDemand)'
                    : e.flowType === 'flow-partner'
                      ? 'url(#edgeGradPartner)'
                      : 'url(#edgeGradPeer)'
                : 'url(#edgeGradDefault)'
            "
            :stroke-width="e.active ? 2.5 : Math.max(1.2, e.strength * 1.8)"
            fill="none"
            :marker-end="e.markerUrl"
            @mouseenter="hoveredEdgeId = e.id"
            @mouseleave="hoveredEdgeId = null"
          />
        </g>
      </svg>

      <!-- Floating Relationship Badge for Active Edge -->
      <div
        v-if="activeFloatingEdge"
        class="floating-edge-pill"
        :style="{
          left: `${activeFloatingEdge.midX}px`,
          top: `${activeFloatingEdge.midY}px`,
        }"
      >
        <span class="pill-pair"
          >{{ activeFloatingEdge.source }} ➔ {{ activeFloatingEdge.target }}</span
        >
        <span class="pill-desc">{{
          activeFloatingEdge.supply_category || relationshipLabel(activeFloatingEdge.relationship)
        }}</span>
      </div>

      <!-- HTML Node Overlays for High-Density Interactive Cards -->
      <div class="nodes-overlay" :style="{ height: `${totalHeight}px` }">
        <div
          v-for="n in layoutNodes"
          :key="n.symbol"
          class="node-card"
          :class="{
            selected: selectedSymbol === n.symbol,
            hovered: hoveredSymbol === n.symbol,
            connected: isNodeConnected(n.symbol),
            focal: n.is_focus,
          }"
          :style="{ left: `${n.x}px`, top: `${n.y}px` }"
          @click="emit('select-node', n.symbol)"
          @mouseenter="hoveredSymbol = n.symbol"
          @mouseleave="hoveredSymbol = null"
        >
          <div class="node-card-top">
            <span class="node-symbol">{{ n.symbol }}</span>
            <span class="node-tier" :class="tierColorClass(n.tier)">
              {{ tierBadgeLabel(n.tier) }}
            </span>
          </div>

          <div class="node-sub" :title="n.sub_industry">{{ n.sub_industry }}</div>

          <div class="node-card-bottom">
            <span class="node-cap">{{ formatMarketCap(n.market_cap_billions) }}</span>
            <span
              v-if="!n.is_focus && n.metrics?.elasticity_score != null"
              class="node-elasticity"
              :class="`tone-${elasticityTone(n.metrics.elasticity_score)}`"
            >
              Sens: {{ n.metrics.elasticity_score.toFixed(0) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chain-graph-container {
  background: var(--void);
  border: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

.graph-header {
  background: var(--void-lift);
  border-bottom: 1px solid var(--rule);
  padding: 0.6rem 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.column-labels {
  display: grid;
  grid-template-columns: repeat(4, 240px);
  gap: 0;
  padding-left: 60px;
}

.col-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.7rem;
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.col-idx {
  font-family: var(--font-mono, monospace);
  color: var(--phosphor);
  font-weight: 600;
}

.col-text {
  font-weight: 500;
}

.graph-header-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

.relationship-legend {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.68rem;
  color: var(--ink-dim);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.legend-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.legend-dot.supply {
  background: var(--phosphor);
}

.legend-dot.demand {
  background: var(--call-hi);
}

.legend-dot.partner {
  background: var(--cat-1);
}

.legend-dot.peer {
  background: var(--ink-faint);
}

.graph-tier-filters {
  display: flex;
  gap: 0.35rem;
}

.tier-filter-btn {
  background: var(--panel);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  font-size: 0.68rem;
  padding: 0.2rem 0.45rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tier-filter-btn:hover {
  background: var(--panel-raise);
  color: var(--ink);
}

.tier-filter-btn.active {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.graph-scroll-surface {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  background-image:
    linear-gradient(to right, var(--grid) var(--hair), transparent var(--hair)),
    linear-gradient(to bottom, var(--grid) var(--hair), transparent var(--hair));
  background-size: 16px 16px;
}

.graph-svg {
  width: 1020px;
  display: block;
}

.chain-edge {
  transition:
    stroke 0.2s ease,
    stroke-width 0.2s ease;
  cursor: pointer;
}

.chain-edge.active {
  stroke-dasharray: 5, 4;
  animation: dashFlow 1.2s linear infinite;
}

@keyframes dashFlow {
  to {
    stroke-dashoffset: -9;
  }
}

.floating-edge-pill {
  position: absolute;
  transform: translate(-50%, -50%);
  background: var(--panel);
  border: 1px solid var(--phosphor);
  padding: 0.25rem 0.55rem;
  border-radius: 4px;
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
  color: var(--ink);
  pointer-events: none;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.18);
  white-space: nowrap;
}

.pill-pair {
  font-weight: 700;
  color: var(--phosphor);
}

.pill-desc {
  color: var(--ink-dim);
  font-size: 0.6rem;
}

.nodes-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 1020px;
  pointer-events: none;
}

.node-card {
  position: absolute;
  width: 180px;
  height: 72px;
  background: var(--panel);
  border: 1px solid var(--rule);
  padding: 0.45rem 0.55rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  cursor: pointer;
  pointer-events: auto;
  transition: all 0.15s ease;
  user-select: none;
}

.node-card:hover {
  background: var(--panel-hi);
  border-color: var(--rule-hi);
  transform: translateY(-1px);
}

.node-card.selected {
  background: var(--panel-raise);
  border-color: var(--phosphor);
  outline: var(--hair) solid var(--phosphor);
}

.node-card.connected {
  border-color: var(--phosphor-dim);
}

.node-card.focal {
  border-left: 3px solid var(--phosphor);
}

.node-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.node-symbol {
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  font-size: 0.85rem;
  color: var(--ink);
}

.node-tier {
  font-size: 0.6rem;
  padding: 0.1rem 0.3rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
}

.node-tier.badge-driver {
  border-color: var(--phosphor-dim);
  color: var(--phosphor);
}

.node-tier.badge-tier1 {
  border-color: var(--call);
  color: var(--call-hi);
}

.node-sub {
  font-size: 0.68rem;
  color: var(--ink-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
}

.node-cap {
  color: var(--ink-faint);
}

.node-elasticity {
  padding: 0.05rem 0.25rem;
  font-weight: 600;
}

.tone-up {
  background: var(--long-wash);
  color: var(--long);
}

.tone-warm {
  background: var(--call-wash);
  color: var(--call-hi);
}

.tone-cool {
  background: var(--panel-raise);
  color: var(--ink-dim);
}

.tone-down {
  background: var(--short-wash);
  color: var(--short);
}
</style>
