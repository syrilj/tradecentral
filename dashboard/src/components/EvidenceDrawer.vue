<script setup lang="ts">
import { useRouter } from 'vue-router'
import type { SupplyChainNode } from '@/api'
import {
  elasticityTone,
  formatCapExSensitivity,
  formatRevConcentration,
  formatMarketCap,
  optionsSkewLabel,
  tierBadgeLabel,
  tierColorClass,
} from '@/chainDisplay'

const props = defineProps<{
  node?: SupplyChainNode | null
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const router = useRouter()

function nav(viewName: string) {
  if (!props.node?.symbol) return
  void router.push({ name: viewName, query: { symbol: props.node.symbol } })
}
</script>

<template>
  <aside class="evidence-drawer" :class="{ 'is-open': open && node }" data-test="evidence-drawer">
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

        <button type="button" class="close-btn" @click="emit('close')">✕</button>
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

.uppercase {
  text-transform: uppercase;
}

.font-mono {
  font-family: var(--font-data);
}
</style>
