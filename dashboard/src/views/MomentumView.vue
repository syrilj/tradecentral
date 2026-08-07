<script setup lang="ts">
import { computed } from 'vue'
import { api, type MomentumCandidate } from '@/api'
import { useResource } from '@/composables/useResource'
import Panel from '@/components/Panel.vue'
import { num, usd } from '@/format'

const scan = useResource(() => api.momentumScan(), { intervalMs: 300_000 })

const candidates = computed<MomentumCandidate[]>(() => scan.data.value?.candidates ?? [])

function pct(v: number | null): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

function rvolTxt(v: number | null): string {
  return v == null ? '—' : `${v.toFixed(1)}×`
}

function floatTxt(shares: number | null): string {
  if (shares == null) return 'n/a'
  return `${(shares / 1_000_000).toFixed(1)}M`
}
</script>

<template>
  <div class="momentum-view">
    <Panel
      label="Momentum Pre-Scan"
      index="14"
      :meta="scan.data.value ? `as of ${scan.data.value.asof}` : ''"
      :live="!scan.error.value"
      flush
    >
      <div class="banner label">
        Pre-market watchlist, not a live feed · Five Pillars pre-scan (price, gap, RVOL, float) against
        {{ scan.data.value ? num(scan.data.value.universe_size, 0) : '—' }} of
        {{ scan.data.value ? num(scan.data.value.expected_universe_size, 0) : '—' }} expected symbols ·
        float known for {{ scan.data.value ? scan.data.value.float_coverage_pct.toFixed(0) : '—' }}%
      </div>

      <p v-if="scan.error.value" class="state label">{{ scan.error.value }}</p>
      <p v-else-if="scan.loading.value && !scan.data.value" class="state label">Loading momentum scan…</p>
      <p v-else-if="!candidates.length" class="state label">
        0 candidates met price + gap + RVOL criteria as of {{ scan.data.value?.asof ?? 'last close' }}.
      </p>

      <table v-else class="mtable">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Price</th>
            <th>Gap</th>
            <th>Day chg</th>
            <th>RVOL</th>
            <th>Float</th>
            <th>Pillars</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in candidates" :key="c.symbol">
            <td class="sym">{{ c.symbol }}</td>
            <td class="fig">{{ usd(c.price) }}</td>
            <td class="fig" :class="{ sweet: c.gap_sweet_spot }">{{ pct(c.gap_pct) }}</td>
            <td class="fig">{{ pct(c.day_change_pct) }}</td>
            <td class="fig">{{ rvolTxt(c.rvol) }}</td>
            <td class="fig">
              <span class="badge" :class="c.float_badge">{{ floatTxt(c.float_shares) }}</span>
            </td>
            <td class="fig">{{ c.pillars_met }}/3</td>
          </tr>
        </tbody>
      </table>
    </Panel>
  </div>
</template>

<style scoped>
.momentum-view {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.banner {
  padding: var(--s2);
  color: var(--ink-dim);
  border-bottom: var(--hair) solid var(--rule-faint);
}
.state {
  padding: var(--s4);
  color: var(--ink-faint);
  text-align: center;
}
.mtable {
  width: 100%;
  border-collapse: collapse;
}
.mtable th {
  text-align: right;
  padding: var(--s2);
  color: var(--ink-faint);
  font-size: var(--t-micro);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-bottom: var(--hair) solid var(--rule);
}
.mtable th:first-child,
.mtable td.sym {
  text-align: left;
}
.mtable td {
  text-align: right;
  padding: var(--s2);
  border-bottom: var(--hair) solid var(--rule-faint);
  font-variant-numeric: tabular-nums;
}
.mtable td.fig.sweet {
  color: var(--phosphor);
  font-weight: 700;
}
.badge {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  font-size: var(--t-micro);
}
.badge.optimal { color: var(--phosphor); border-color: var(--phosphor-dim); }
.badge.qualifies { color: var(--ink); }
.badge.no { color: var(--ink-faint); }
.badge.unknown { color: var(--ink-ghost); font-style: italic; }
</style>
