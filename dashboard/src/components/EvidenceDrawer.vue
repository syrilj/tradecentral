<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import type { SupplyChainEdge, SupplyChainNode } from '@/api'
import {
  elasticityTone,
  formatCapExSensitivity,
  formatRevConcentration,
  formatMarketCap,
  formatContractValue,
  optionsSkewLabel,
  tierBadgeLabel,
  tierColorClass,
  relationshipLabel,
  strengthTone,
  generateRelationshipNarrative,
} from '@/chainDisplay'

const props = withDefaults(
  defineProps<{
    node?: SupplyChainNode | null
    open: boolean
    edges?: SupplyChainEdge[]
    focalNode?: SupplyChainNode | null
    incidentEdges?: SupplyChainEdge[]
  }>(),
  {
    node: null,
    edges: () => [],
    focalNode: null,
    incidentEdges: () => [],
  },
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'focus-chain', symbol: string): void
}>()

const router = useRouter()

function nav(viewName: string) {
  if (!props.node?.symbol) return
  void router.push({ name: viewName, query: { symbol: props.node.symbol } })
}

const activeIncidentEdges = computed<SupplyChainEdge[]>(() => {
  if (props.incidentEdges && props.incidentEdges.length > 0) {
    return props.incidentEdges
  }
  if (props.edges && props.edges.length > 0 && props.node?.symbol) {
    const sym = props.node.symbol
    return props.edges.filter((e) => e.source === sym || e.target === sym)
  }
  return []
})

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) {
    emit('close')
  }
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('keydown', onGlobalKeydown)
  }
})

onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', onGlobalKeydown)
  }
})
</script>

<template>
  <!-- Backdrop scrim for dismissal & focus trapping context -->
  <div
    v-if="open && node"
    class="drawer-backdrop"
    data-test="drawer-backdrop"
    aria-hidden="true"
    @click="emit('close')"
  />

  <aside
    class="evidence-drawer"
    :class="{ 'is-open': open && node }"
    data-test="evidence-drawer"
    role="dialog"
    aria-modal="true"
    :aria-label="node ? `Entity Evidence and Supply Chain Details: ${node.symbol} - ${node.name}` : 'Entity Evidence and Supply Chain Details'"
    tabindex="-1"
    @keydown.esc="emit('close')"
  >
    <div v-if="node" class="drawer-content">
      <!-- Drawer Header -->
      <div class="drawer-header">
        <div class="header-main">
          <div class="ticker-line">
            <span class="ticker-sym">{{ node.symbol }}</span>
            <span class="ticker-tier" :class="tierColorClass(node.tier)">
              {{ tierBadgeLabel(node.tier) }}
            </span>
          </div>
          <div class="company-name">{{ node.name }}</div>
          <div class="sub-industry">
            {{ node.sub_industry }} · {{ formatMarketCap(node.market_cap_billions) }}
          </div>
        </div>

        <button
          type="button"
          class="close-btn"
          aria-label="Close drawer"
          title="Close drawer"
          @click="emit('close')"
        >
          ✕
        </button>
      </div>

      <!-- Prominent Relationship Rationale & Contract Context Section -->
      <div class="relationship-section" data-test="relationship-rationale">
        <div class="section-title">
          <span>RELATIONSHIP RATIONALE & CONTRACT CONTEXT</span>
        </div>

        <div v-if="activeIncidentEdges.length" class="connections-list">
          <div
            v-for="edge in activeIncidentEdges"
            :key="edge.id"
            class="connection-card"
          >
            <div class="connection-header">
              <span class="connection-pair font-mono">{{ edge.source }} ➔ {{ edge.target }}</span>
              <span class="connection-rel-pill">
                {{ relationshipLabel(edge.relationship) }}
              </span>
              <span v-if="edge.supply_category" class="connection-cat-badge">
                {{ edge.supply_category }}
              </span>
            </div>

            <div class="connection-metrics-grid">
              <div class="conn-metric">
                <span class="conn-k">Est. Annual Contract:</span>
                <span class="conn-v font-mono">{{ formatContractValue(edge.annual_contract_value_est_m) }}</span>
              </div>
              <div class="conn-metric">
                <span class="conn-k">Link Strength:</span>
                <div class="strength-meter-wrap">
                  <div class="strength-track">
                    <div
                      class="strength-fill"
                      :class="`strength-${strengthTone(edge.strength)}`"
                      :style="{ width: `${Math.round(edge.strength * 100)}%` }"
                    />
                  </div>
                  <span class="strength-val font-mono">{{ Math.round(edge.strength * 100) }}%</span>
                </div>
              </div>
            </div>

            <div class="connection-narrative">
              {{ generateRelationshipNarrative(edge, node) }}
            </div>
          </div>
        </div>

        <div v-else class="connection-fallback-panel">
          <div class="fallback-header">
            <span class="fallback-role-tag">
              {{ node.is_focus || node.tier === 'mega_driver' ? 'CORE ECOSYSTEM ANCHOR' : tierBadgeLabel(node.tier) }}
            </span>
          </div>
          <p class="fallback-narrative">
            <template v-if="node.is_focus || node.tier === 'mega_driver'">
              {{ node.name }} ({{ node.symbol }}) is the central anchor entity for this value chain. Capital expenditures, architectural roadmap decisions, and procurement volume flow through this driver to upstream Tier 1/2 suppliers and downstream enterprise customers.
            </template>
            <template v-else>
              {{ node.name }} ({{ node.symbol }}) operates within {{ node.sub_industry }} ({{ node.sector }}). Financial elasticity and revenue concentration propagate through correlated demand shifts across connected supply chain nodes.
            </template>
          </p>
        </div>
      </div>

      <!-- Quick Metric Tiles -->
      <div class="metrics-grid">
        <div class="metric-card">
          <span class="metric-label">ELASTICITY SCORE</span>
          <span class="metric-val" :class="`val-${elasticityTone(node.metrics?.elasticity_score)}`">
            {{ node.metrics?.elasticity_score?.toFixed(1) ?? '—' }}
          </span>
        </div>

        <div class="metric-card">
          <span class="metric-label">CAPEX SENSITIVITY</span>
          <span class="metric-val text-long">
            {{ formatCapExSensitivity(node.metrics?.capex_sensitivity) }}
          </span>
        </div>

        <div class="metric-card">
          <span class="metric-label">REV CONCENTRATION</span>
          <span class="metric-val text-call">
            {{ formatRevConcentration(node.metrics?.revenue_concentration_pct) }}
          </span>
        </div>

        <div class="metric-card">
          <span class="metric-label">OPTIONS SKEW</span>
          <span
            v-if="optionsSkewLabel(node.metrics?.options_skew)"
            class="metric-val text-sm"
            :class="`text-${optionsSkewLabel(node.metrics?.options_skew)!.tone}`"
          >
            {{ optionsSkewLabel(node.metrics?.options_skew)!.label }}
          </span>
          <span v-else class="metric-val text-sm">—</span>
        </div>
      </div>

      <!-- Additional Valuation & Catalyst Meta -->
      <div class="meta-strip">
        <div class="meta-cell">
          <span class="cell-k">Forward P/E:</span>
          <span class="cell-v">{{
            node.metrics?.forward_pe ? `${node.metrics.forward_pe.toFixed(1)}x` : '—'
          }}</span>
        </div>
        <div class="meta-cell">
          <span class="cell-k">Gross Margin:</span>
          <span class="cell-v uppercase">{{ node.metrics?.gross_margin_trend ?? '—' }}</span>
        </div>
        <div class="meta-cell">
          <span class="cell-k">Next Catalyst / ER:</span>
          <span class="cell-v font-mono">{{
            node.metrics?.next_earnings_date ?? 'Unconfirmed'
          }}</span>
        </div>
      </div>

      <!-- Evidence & Citations Stream -->
      <div class="evidence-section">
        <div class="section-title">
          <span>VERBATIM TRANSCRIPT & FILING CITATIONS ({{ node.evidence?.length ?? 0 }})</span>
        </div>

        <div class="citations-list">
          <div v-for="(ev, idx) in node.evidence" :key="idx" class="citation-card">
            <div class="citation-meta">
              <span class="source-tag uppercase">{{ ev.source_type.replace('_', ' ') }}</span>
              <span class="period-tag font-mono">{{ ev.period }} ({{ ev.filing_date }})</span>
              <span v-if="ev.confidence" class="confidence-tag">
                {{ Math.round(ev.confidence * 100) }}% match
              </span>
            </div>

            <div v-if="ev.speaker" class="speaker-tag">Speaker: {{ ev.speaker }}</div>

            <!-- No verbatim quote is rendered unless a real quotation exists. -->
            <blockquote v-if="ev.quote" class="quote-body">"{{ ev.quote }}"</blockquote>

            <div v-if="ev.context" class="quote-context">
              <span class="context-k">Context:</span> {{ ev.context }}
            </div>
          </div>

          <div v-if="!node.evidence?.length" class="no-citations">
            No direct SEC or transcript quotation records attached for this node.
          </div>
        </div>
      </div>

      <!-- Trading Desk Navigation Links -->
      <div class="desk-actions">
        <button
          type="button"
          class="desk-btn primary-focus-btn"
          title="Focus value chain on this stock"
          @click="emit('focus-chain', node.symbol)"
        >
          ⚡ Focus Value Chain on {{ node.symbol }}
        </button>
        <button type="button" class="desk-btn" @click="nav('options')">
          Options Vol & GEX Tape →
        </button>
        <button type="button" class="desk-btn" @click="nav('market')">
          Market Profile & Filings →
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(2px);
  z-index: calc(var(--z-overlay, 120) - 1);
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.evidence-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 440px;
  max-width: 90vw;
  background: var(--panel);
  border-left: 1px solid var(--rule-hi);
  z-index: var(--z-overlay); /* was 120, above the --z-toast ceiling */
  transform: translateX(100%);
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.4);
  display: flex;
  flex-direction: column;
}

.evidence-drawer.is-open {
  transform: translateX(0);
}

.drawer-content {
  height: 100%;
  overflow-y: auto;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 0.85rem;
}

.ticker-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ticker-sym {
  font-family: var(--font-data);
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--ink);
}

.ticker-tier {
  font-size: 0.65rem;
  padding: 0.15rem 0.4rem;
  text-transform: uppercase;
  background: var(--void-lift);
  border: 1px solid var(--rule);
}

.company-name {
  font-size: 0.88rem;
  color: var(--ink-soft);
  margin-top: 0.15rem;
}

.sub-industry {
  font-size: 0.72rem;
  color: var(--ink-faint);
  margin-top: 0.1rem;
}

.close-btn {
  background: transparent;
  border: 1px solid var(--rule);
  color: var(--ink-faint);
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.close-btn:hover {
  border-color: var(--ink);
  color: var(--ink);
}

.close-btn:focus-visible {
  outline: 2px solid var(--accent, var(--phosphor));
  outline-offset: 2px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.metric-card {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  padding: 0.5rem 0.65rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.metric-label {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-val {
  font-family: var(--font-data);
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--ink);
}

.val-up {
  color: var(--long);
}

.val-warm {
  color: var(--call-hi);
}

.text-long {
  color: var(--long);
}

.text-call {
  color: var(--call-hi);
}

.text-sm {
  font-size: 0.82rem;
}

.meta-strip {
  background: var(--void);
  border: 1px solid var(--rule);
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.72rem;
}

.meta-cell {
  display: flex;
  justify-content: space-between;
}

.cell-k {
  color: var(--ink-faint);
}

.cell-v {
  color: var(--ink);
  font-weight: 500;
}

.evidence-section {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.section-title {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--phosphor);
  letter-spacing: 0.06em;
}

.citations-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.citation-card {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.citation-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.65rem;
}

.source-tag {
  background: var(--panel-raise);
  color: var(--phosphor);
  padding: 0.1rem 0.35rem;
}

.period-tag {
  color: var(--ink-faint);
}

.confidence-tag {
  margin-left: auto;
  color: var(--ink-faint);
  font-family: var(--font-data);
}

.speaker-tag {
  font-size: 0.7rem;
  color: var(--ink-soft);
  font-weight: 500;
}

.quote-body {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.4;
  color: var(--ink);
  background: rgba(0, 0, 0, 0.2);
  padding: 0.5rem;
  border-left: 1px solid var(--phosphor-dim);
}

.quote-context {
  font-size: 0.68rem;
  color: var(--ink-faint);
}

.context-k {
  font-weight: 600;
  color: var(--ink-soft);
}

.no-citations {
  color: var(--ink-faint);
  font-size: 0.75rem;
  text-align: center;
  padding: 1rem;
}

.desk-actions {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: auto;
  padding-top: 0.75rem;
  border-top: 1px solid var(--rule);
}

.desk-btn {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink);
  font-size: 0.75rem;
  padding: 0.5rem;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.desk-btn:hover {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.primary-focus-btn {
  background: var(--phosphor-wash);
  color: var(--phosphor);
  border-color: var(--phosphor-dim);
  font-weight: 600;
}

.primary-focus-btn:hover {
  background: var(--phosphor);
  color: var(--void);
}

.desk-btn:focus-visible,
.primary-focus-btn:focus-visible {
  outline: 2px solid var(--accent, var(--phosphor));
  outline-offset: 2px;
}

.relationship-section {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.connections-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.connection-card {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  transition: border-color 0.15s ease;
}

.connection-card:hover {
  border-color: var(--rule-hi);
}

.connection-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.connection-pair {
  font-weight: 700;
  font-size: 0.85rem;
  color: var(--phosphor);
}

.connection-rel-pill {
  font-size: var(--t-nano);
  padding: 0.1rem 0.35rem;
  text-transform: uppercase;
  background: var(--panel-raise);
  color: var(--call-hi);
  border: 1px solid var(--rule);
  letter-spacing: 0.03em;
}

.connection-cat-badge {
  font-size: var(--t-nano);
  padding: 0.1rem 0.35rem;
  background: var(--void);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
}

.connection-metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
  background: var(--void);
  border: 1px solid var(--rule);
  padding: 0.45rem 0.6rem;
  font-size: 0.7rem;
}

.conn-metric {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.conn-k {
  font-size: var(--t-nano);
  color: var(--ink-faint);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.conn-v {
  color: var(--ink);
  font-weight: 600;
}

.strength-meter-wrap {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}

.strength-track {
  flex: 1;
  height: 6px;
  background: var(--panel-raise);
  border-radius: 3px;
  overflow: hidden;
}

.strength-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.strength-high {
  background: var(--long);
}

.strength-mid {
  background: var(--call-hi);
}

.strength-low {
  background: var(--ink-dim);
}

.strength-val {
  font-size: 0.7rem;
  color: var(--ink-soft);
  font-weight: 600;
  min-width: 32px;
  text-align: right;
}

.connection-narrative {
  font-size: 0.72rem;
  color: var(--ink-soft);
  line-height: 1.45;
  background: rgba(0, 0, 0, 0.18);
  border-left: 2px solid var(--phosphor);
  padding: 0.45rem 0.6rem;
}

.connection-fallback-panel {
  background: var(--void-lift);
  border: 1px solid var(--rule);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.fallback-header {
  display: flex;
  align-items: center;
}

.fallback-role-tag {
  font-size: var(--t-nano);
  padding: 0.1rem 0.35rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--panel-raise);
  border: 1px solid var(--rule);
  color: var(--phosphor);
  font-weight: 600;
}

.fallback-narrative {
  margin: 0;
  font-size: 0.74rem;
  color: var(--ink-soft);
  line-height: 1.45;
}

.uppercase {
  text-transform: uppercase;
}

.font-mono {
  font-family: var(--font-data);
}
</style>
