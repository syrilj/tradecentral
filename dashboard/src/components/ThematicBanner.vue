<script setup lang="ts">
import { computed } from 'vue'
import type { ThematicSummary, SupplyChainThemeSummary, RelatedTheme } from '@/api'
import { formatMarketCap } from '@/chainDisplay'

const props = defineProps<{
  summary?: ThematicSummary | null
  themes?: SupplyChainThemeSummary[]
  currentThemeId?: string
  loading?: boolean
}>()

const relatedThemes = computed<RelatedTheme[]>(() => props.summary?.related_themes ?? [])

const emit = defineEmits<{
  (e: 'select-theme', themeId: string): void
  (e: 'select-ticker', symbol: string): void
}>()
</script>

<template>
  <div class="thematic-banner" data-test="thematic-banner">
    <!-- Top Row: 8 Thematic Frontiers Switcher & Total Valuation -->
    <div class="banner-top">
      <div class="theme-pills">
        <button
          v-for="t in themes"
          :key="t.id"
          type="button"
          class="theme-pill"
          :class="{ active: currentThemeId === t.id }"
          @click="emit('select-theme', t.id)"
        >
          <span class="pill-name">{{ t.theme_name }}</span>
          <span class="pill-count">{{ t.node_count }}</span>
        </button>
      </div>

      <div v-if="summary" class="banner-meta">
        <div class="meta-item">
          <span class="meta-label">Ecosystem Total Cap</span>
          <span class="meta-value">{{
            formatMarketCap(summary.total_ecosystem_market_cap_b)
          }}</span>
        </div>
      </div>
    </div>

    <!-- Narrative & Catalyst Timeline Strip -->
    <div v-if="summary" class="banner-narrative">
      <div class="narrative-text">
        <div class="narrative-header-row">
          <span class="narrative-tag">CAPEX & DEMAND CASCADE</span>
          <span class="active-theme-title">{{ summary.theme_name }}</span>
        </div>
        <p>{{ summary.capex_catalyst_narrative }}</p>
      </div>

      <div v-if="summary.catalyst_timeline?.length" class="catalyst-timeline">
        <div class="timeline-header">
          <span class="timeline-title"
            >Upcoming Catalyst Milestones ({{ summary.catalyst_timeline.length }})</span
          >
        </div>
        <div class="timeline-track">
          <div v-for="(evt, i) in summary.catalyst_timeline" :key="i" class="timeline-card">
            <div class="card-date">{{ evt.date }}</div>
            <div class="card-event">{{ evt.event }}</div>
            <div class="card-tickers">
              <button
                v-for="sym in evt.impacted_tickers"
                :key="sym"
                type="button"
                class="ticker-chip"
                @click.stop="emit('select-ticker', sym)"
              >
                {{ sym }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Related Themes: shared-ticker connective tissue -->
    <div v-if="relatedThemes.length" class="related-themes">
      <span class="related-label">CONNECTED VALUE CHAINS</span>
      <div class="related-track">
        <button
          v-for="rel in relatedThemes"
          :key="rel.id"
          type="button"
          class="related-pill"
          @click="emit('select-theme', rel.id)"
        >
          <span class="related-name">{{ rel.theme_name }}</span>
          <span class="related-shared">{{ rel.shared_tickers.join(' · ') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.thematic-banner {
  background: var(--panel);
  border: 1px solid var(--rule);
  padding: 0.9rem 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  font-family: var(--font-ui);
}

.banner-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.theme-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  max-width: calc(100% - 200px);
}

@media (max-width: 1024px) {
  .theme-pills {
    max-width: 100%;
  }
}

.theme-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.28rem 0.55rem;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  font-size: 0.72rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.theme-pill:hover {
  background: var(--panel-raise);
  color: var(--ink);
  border-color: var(--rule-hi);
}

.theme-pill.active {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
  font-weight: 600;
}

.pill-count {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  opacity: 0.85;
  padding: 0.05rem 0.25rem;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 1px;
}

.banner-meta {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.meta-item {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.meta-label {
  font-size: var(--t-nano);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-faint);
}

.meta-value {
  font-family: var(--font-data);
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--ink);
}

.banner-narrative {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 1.15rem;
  padding-top: 0.7rem;
  border-top: 1px solid var(--rule-faint);
}

@media (max-width: 1024px) {
  .banner-narrative {
    grid-template-columns: 1fr;
  }
}

.narrative-header-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.35rem;
}

.narrative-tag {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--phosphor);
}

.active-theme-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ink);
}

.narrative-text p {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.45;
  color: var(--ink-soft);
}

.catalyst-timeline {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.timeline-header {
  font-size: var(--t-nano);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-faint);
}

.timeline-track {
  display: flex;
  gap: 0.45rem;
  overflow-x: auto;
  padding-bottom: 0.2rem;
}

.timeline-card {
  flex: 0 0 auto;
  min-width: 185px;
  max-width: 240px;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  padding: 0.45rem 0.6rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.card-date {
  font-family: var(--font-data);
  font-size: 0.65rem;
  color: var(--phosphor-dim);
  font-weight: 600;
}

.card-event {
  font-size: 0.7rem;
  color: var(--ink);
  line-height: 1.25;
  white-space: normal;
}

.card-tickers {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.15rem;
}

.ticker-chip {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  padding: 0.1rem 0.3rem;
  background: var(--panel-raise);
  border: 1px solid var(--rule-hi);
  color: var(--ink-dim);
  cursor: pointer;
}

.ticker-chip:hover {
  background: var(--phosphor-wash);
  border-color: var(--phosphor);
  color: var(--phosphor);
}

.related-themes {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding-top: 0.7rem;
  border-top: 1px solid var(--rule-faint);
}

.related-label {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}

.related-track {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.related-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.55rem;
  background: var(--void-lift);
  border: 1px solid var(--rule);
  color: var(--ink-dim);
  font-size: 0.7rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.related-pill:hover {
  background: var(--panel-raise);
  color: var(--ink);
  border-color: var(--rule-hi);
}

.related-name {
  font-weight: 600;
  color: var(--ink);
}

.related-shared {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  color: var(--phosphor-dim);
}
</style>
