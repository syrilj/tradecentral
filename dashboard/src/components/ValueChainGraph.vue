<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SupplyChainEdge, SupplyChainNode, SupplyTier } from '@/api'
import { elasticityTone, tierBadgeLabel, tierColorClass, formatMarketCap } from '@/chainDisplay'

const props = defineProps<{
  nodes: SupplyChainNode[]
  edges: SupplyChainEdge[]
  selectedSymbol?: string | null
}>()

const emit = defineEmits<{
  (e: 'select-node', symbol: string): void
}>()

const hoveredSymbol = ref<string | null>(null)
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
  if (tierFilter.value === 'driver') return props.nodes.filter((n) => n.tier === 'mega_driver' || n.tier === 'horizontal_enabler')
  if (tierFilter.value === 'customer') return props.nodes.filter((n) => n.tier === 'downstream_customer')
  return props.nodes
})

const layoutNodes = computed((): LayoutNode[] => {
  const cols: SupplyChainNode[][] = [[], [], [], []]
  for (const n of filteredNodes.value) {
    const colIdx = tierToColumn(n.tier)
    cols[colIdx].push(n)
  }

  const result: LayoutNode[] = []
  const colWidth = 240
  const startX = 60
  const cardHeight = 72
  const gapY = 16

  cols.forEach((colNodes, colIdx) => {
    colNodes.forEach((node, rowIdx) => {
      result.push({
        ...node,
        col: colIdx,
        row: rowIdx,
        x: startX + colIdx * colWidth,
        y: 40 + rowIdx * (cardHeight + gapY),
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
  return Math.max(520, 50 + maxRows * (72 + 16) + 40)
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
}

const computedEdges = computed((): ComputedEdge[] => {
  return props.edges
    .map((e) => {
      const src = nodeMap.value.get(e.source)
      const tgt = nodeMap.value.get(e.target)
      if (!src || !tgt) return null

      const x1 = src.x + 180
      const y1 = src.y + 36
      const x2 = tgt.x
      const y2 = tgt.y + 36

      const dx = Math.abs(x2 - x1) * 0.5
      const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`

      const active =
        props.selectedSymbol === e.source ||
        props.selectedSymbol === e.target ||
        hoveredSymbol.value === e.source ||
        hoveredSymbol.value === e.target

      return {
        ...e,
        d,
        active,
      }
    })
    .filter(Boolean) as ComputedEdge[]
})

function isNodeConnected(symbol: string): boolean {
  if (!props.selectedSymbol && !hoveredSymbol.value) return false
  const activeSym = hoveredSymbol.value || props.selectedSymbol
  if (symbol === activeSym) return true
  return props.edges.some(
    (e) => (e.source === activeSym && e.target === symbol) || (e.target === activeSym && e.source === symbol),
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
          Tier 1 (Optics/Memory)
        </button>
        <button
          type="button"
          class="tier-filter-btn"
          :class="{ active: tierFilter === 'driver' }"
          @click="tierFilter = 'driver'"
        >
          Drivers & Power
        </button>
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
            <stop offset="0%" stop-color="var(--rule-hi)" stop-opacity="0.4" />
            <stop offset="100%" stop-color="var(--rule-hi)" stop-opacity="0.8" />
          </linearGradient>
          <linearGradient id="edgeGradActive" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="var(--phosphor-dim)" stop-opacity="0.8" />
            <stop offset="100%" stop-color="var(--phosphor)" stop-opacity="1" />
          </linearGradient>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="6"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="var(--phosphor)" />
          </marker>
        </defs>

        <!-- Edges -->
        <g class="edges-layer">
          <path
            v-for="e in computedEdges"
            :key="e.id"
            :d="e.d"
            class="chain-edge"
            :class="{ active: e.active }"
            :stroke="e.active ? 'url(#edgeGradActive)' : 'url(#edgeGradDefault)'"
            :stroke-width="e.active ? 2.5 : Math.max(1, e.strength * 2)"
            fill="none"
            :marker-end="e.active ? 'url(#arrow)' : undefined"
          />
        </g>
      </svg>

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

          <div class="node-sub">{{ n.sub_industry }}</div>

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
  min-width: 1020px;
  background-image: radial-gradient(var(--grid) 1px, transparent 1px);
  background-size: 16px 16px;
}

.graph-svg {
  width: 1020px;
  display: block;
}

.chain-edge {
  transition: stroke 0.2s ease, stroke-width 0.2s ease;
}

.chain-edge.active {
  stroke-dasharray: 4, 4;
  animation: dashFlow 1s linear infinite;
}

@keyframes dashFlow {
  to {
    stroke-dashoffset: -8;
  }
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
  box-shadow: 0 0 0 1px var(--phosphor);
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
