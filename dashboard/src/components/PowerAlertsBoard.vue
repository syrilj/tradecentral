<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { MarketFlowPrint, UnusualFlowRow } from '@/api'
import { age, compact, DASH, shortDate, signedPct, usd } from '@/format'
import {
  alertPathPoints,
  buildPowerAlerts,
  fiveDayTracker,
  largestOrders,
  loadAlertHistory,
  persistPowerAlertHistory,
  signedStreak,
  type PowerAlert,
  type PowerAlertLean,
} from '@/flowPowerAlerts'
import { watchlistHas } from '@/watchlist'
import AppIcon from '@/components/AppIcon.vue'
import HelpTip from '@/components/HelpTip.vue'

type AlertFilter = 'all' | 'signed-bullish' | 'signed-bearish' | 'call' | 'put' | 'cheap' | 'book'

const props = defineProps<{
  prints: MarketFlowPrint[]
  rows: UnusualFlowRow[]
  book: string[]
  asof: string
}>()

const emit = defineEmits<{
  openSymbol: [symbol: string]
}>()

const FILTERS: Array<{ id: AlertFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'signed-bullish', label: 'Signed long' },
  { id: 'signed-bearish', label: 'Signed short' },
  { id: 'call', label: 'Calls' },
  { id: 'put', label: 'Puts' },
  { id: 'cheap', label: 'Cheap $0.20–0.70' },
  { id: 'book', label: 'My book' },
]

const history = ref(loadAlertHistory())
const liveAlerts = ref<PowerAlert[]>([])
const filter = ref<AlertFilter>('all')
const selectedKey = ref<string | null>(null)

watch(
  () => [props.prints, props.rows] as const,
  () => {
    const next = buildPowerAlerts({
      prints: props.prints,
      rows: props.rows,
      history: history.value,
    })
    liveAlerts.value = next.alerts
    history.value = persistPowerAlertHistory(next.history)
  },
  { immediate: true },
)

const alerts = computed(() => {
  const rows = liveAlerts.value
  if (filter.value === 'all') return rows
  if (filter.value === 'cheap') return rows.filter((row) => row.cheap)
  if (filter.value === 'book') return rows.filter((row) => watchlistHas(props.book, row.symbol))
  if (filter.value === 'call' || filter.value === 'put') {
    return rows.filter((row) => row.right === filter.value)
  }
  return rows.filter((row) => row.lean === filter.value)
})

const selected = computed<PowerAlert | null>(() => {
  if (!alerts.value.length) return null
  return alerts.value.find((row) => row.key === selectedKey.value) ?? alerts.value[0]
})

watch(alerts, (rows) => {
  if (selectedKey.value && rows.some((row) => row.key === selectedKey.value)) return
  selectedKey.value = rows[0]?.key ?? null
})

const tracker = computed(() => {
  const alert = selected.value
  if (!alert) return null
  return fiveDayTracker({
    symbol: alert.symbol,
    history: history.value,
    currentSpot: alert.currentSpot,
  })
})

const streak = computed(() => {
  const alert = selected.value
  if (!alert) return null
  return signedStreak(history.value, alert.symbol)
})

const orders = computed(() => {
  const alert = selected.value
  if (!alert) return []
  return largestOrders(props.prints, alert.symbol, 5)
})

const path = computed(() => {
  const alert = selected.value
  if (!alert) return []
  return alertPathPoints(props.prints, alert.symbol)
})

const chart = computed(() => {
  const points = path.value
  if (points.length < 2) return null
  const width = 320
  const height = 88
  const pad = 6
  const ys = points.map((point) => point.y)
  const min = Math.min(...ys)
  const max = Math.max(...ys)
  const range = max - min || 1
  const step = (width - pad * 2) / (points.length - 1)
  const coords = points.map((point, index) => {
    const x = pad + index * step
    const y = height - pad - ((point.y - min) / range) * (height - pad * 2)
    return { ...point, x, y }
  })
  const line = coords
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
    .join(' ')
  const area = `${line} L ${coords[coords.length - 1].x.toFixed(1)} ${height - pad} L ${coords[0].x.toFixed(1)} ${height - pad} Z`
  const mark = selected.value
    ? (coords.find((point) => point.key === selected.value?.key) ?? coords[0])
    : null
  return { width, height, line, area, mark, min, max }
})

const maxDayCount = computed(() =>
  Math.max(1, ...(tracker.value?.days.map((day) => day.count) ?? [1])),
)

function leanClass(lean: PowerAlertLean): string {
  if (lean === 'signed-bullish') return 'token-long'
  if (lean === 'signed-bearish') return 'token-short'
  if (lean === 'call') return 'call-id'
  if (lean === 'put') return 'put-id'
  return 'token-unsigned'
}

function money(value: number | null | undefined): string {
  return value == null ? DASH : `$${compact(value)}`
}

function moveLabel(value: number | null | undefined): string {
  return value == null ? DASH : signedPct(value * 100, 2)
}
</script>

<template>
  <section class="power-alerts ticked live rise" aria-label="Power alerts">
    <header class="alerts-head">
      <div>
        <span class="label section-kicker">
          <AppIcon name="alert" :size="13" />
          Power alerts
        </span>
        <h2>
          Notable unusual prints
          <HelpTip
            label="Power Alerts"
            text="Attention rank from premium, sweeps, vol/OI, heat, and unusual flags. Call/put is identity. Signed long/short requires a provider buy/sell. Underlying move is versus the first print in this browser. Option P/L stays blank until both fills are measured. Not a trade authorization. No dark-pool tape."
            align="left"
          />
        </h2>
        <p>
          Strength is an ordinal desk rank, not a probability. Cheap contracts are fills between
          $0.20 and $0.70 when the feed sends a price.
        </p>
      </div>
      <div class="head-meta label">
        <span>{{ alerts.length }} SHOWING</span>
        <span>{{ asof ? `AS OF ${age(asof)}` : 'NO ASOF' }}</span>
      </div>
    </header>

    <div class="alert-filters" role="tablist" aria-label="Power alert filters">
      <button
        v-for="item in FILTERS"
        :key="item.id"
        type="button"
        role="tab"
        :aria-selected="filter === item.id"
        :class="{ active: filter === item.id }"
        @click="filter = item.id"
      >
        {{ item.label }}
      </button>
    </div>

    <div v-if="!alerts.length" class="empty-alerts">
      <strong>No notable prints in this window.</strong>
      <p>
        Alerts fire on unusual, sweep, block, vol &gt; OI, $100k+ premium, or heat. Lower the
        premium floor or wait for the next provider sample.
      </p>
    </div>

    <template v-else>
      <div class="card-rail" role="list">
        <button
          v-for="alert in alerts"
          :key="alert.key"
          type="button"
          class="alert-card"
          role="listitem"
          :class="[{ active: selected?.key === alert.key }, leanClass(alert.lean)]"
          :aria-pressed="selected?.key === alert.key"
          @click="selectedKey = alert.key"
        >
          <span class="card-top">
            <span class="lean-chip label" :class="leanClass(alert.lean)">{{
              alert.leanLabel
            }}</span>
            <span class="strength fig">{{ alert.strength }}</span>
          </span>
          <strong class="fig symbol">{{ alert.symbol }}</strong>
          <span class="contract label">
            {{ alert.right.toUpperCase() }}
            {{ alert.strike != null ? usd(alert.strike, 0) : DASH }}
            · {{ shortDate(alert.expiry) }}
          </span>
          <span class="card-metrics">
            <b class="fig">{{ money(alert.premium) }}</b>
            <span class="order-chip label" :class="alert.orderClass">{{ alert.orderLabel }}</span>
          </span>
          <span v-if="alert.cheap" class="cheap label">CHEAP FILL</span>
          <small>{{ alert.timestamp ? age(alert.timestamp) : DASH }}</small>
        </button>
      </div>

      <article v-if="selected" class="alert-detail ticked">
        <header class="detail-head">
          <div>
            <span class="label">Selected alert</span>
            <h3 class="fig">
              {{ selected.symbol }} {{ selected.right.toUpperCase() }}
              {{ selected.strike != null ? usd(selected.strike, 0) : DASH }}
            </h3>
            <p>{{ selected.why.join(' · ') || 'Notable print in the current window.' }}</p>
          </div>
          <button
            type="button"
            class="open-setup label"
            @click="emit('openSymbol', selected.symbol)"
          >
            OPEN LIVE SETUP →
          </button>
        </header>

        <div class="detail-grid">
          <section class="chart-pane">
            <span class="label">Underlying vs trigger</span>
            <svg
              v-if="chart && chart.mark"
              class="alert-chart"
              :viewBox="`0 0 ${chart.width} ${chart.height}`"
              role="img"
              :aria-label="`${selected.symbol} underlying path in this window`"
            >
              <path :d="chart.area" class="chart-fill" />
              <path :d="chart.line" class="chart-line" />
              <circle :cx="chart.mark.x" :cy="chart.mark.y" r="4" class="chart-mark" />
            </svg>
            <p v-else class="missing">
              Need two measured underlying prints in this window for a path.
            </p>
            <small class="label">Marker is the first print of this alert, not a forecast.</small>
          </section>

          <section>
            <span class="label">Contract</span>
            <dl class="facts">
              <div>
                <dt>Expiry / DTE</dt>
                <dd class="fig">{{ shortDate(selected.expiry) }} · {{ selected.dte ?? DASH }}d</dd>
              </div>
              <div>
                <dt>Fill</dt>
                <dd class="fig">{{ selected.price != null ? usd(selected.price, 2) : DASH }}</dd>
              </div>
              <div>
                <dt>Contracts</dt>
                <dd class="fig">{{ selected.contracts ?? DASH }}</dd>
              </div>
              <div>
                <dt>Vol / OI</dt>
                <dd class="fig">
                  {{ selected.volOi != null ? `${selected.volOi.toFixed(1)}×` : DASH }}
                </dd>
              </div>
            </dl>
          </section>

          <section>
            <span class="label">Vs first print</span>
            <dl class="facts">
              <div>
                <dt>First spot</dt>
                <dd class="fig">
                  {{ selected.firstSpot != null ? usd(selected.firstSpot, 2) : DASH }}
                </dd>
              </div>
              <div>
                <dt>Current spot</dt>
                <dd class="fig">
                  {{ selected.currentSpot != null ? usd(selected.currentSpot, 2) : DASH }}
                </dd>
              </div>
              <div>
                <dt>Underlying</dt>
                <dd
                  class="fig"
                  :class="
                    selected.spotMovePct != null && selected.spotMovePct >= 0
                      ? 'token-long'
                      : selected.spotMovePct != null
                        ? 'token-short'
                        : ''
                  "
                >
                  {{ moveLabel(selected.spotMovePct) }}
                </dd>
              </div>
              <div>
                <dt>Contract price</dt>
                <dd class="fig">{{ moveLabel(selected.premiumMovePct) }}</dd>
              </div>
            </dl>
          </section>

          <section class="tracker-pane">
            <span class="label">5-day alert count</span>
            <div v-if="tracker" class="day-bars" aria-label="Five-day alert counts">
              <div v-for="day in tracker.days" :key="day.date" class="day-col">
                <span class="bar-wrap">
                  <i
                    :style="{ height: `${Math.round((day.count / maxDayCount) * 100)}%` }"
                    :class="{ on: day.count > 0 }"
                  />
                </span>
                <strong class="fig">{{ day.count }}</strong>
                <small>{{ day.date.slice(5) }}</small>
              </div>
            </div>
            <p v-if="streak" class="streak label">
              {{ streak.count }} consecutive
              {{ streak.lean === 'signed-bullish' ? 'signed-long' : 'signed-short' }} alerts for
              {{ selected.symbol }}
            </p>
            <p v-else class="missing">No consecutive signed-side streak for this name.</p>
          </section>

          <section class="orders-pane">
            <span class="label">Largest orders today</span>
            <ul v-if="orders.length">
              <li v-for="row in orders" :key="`${row.timestamp}-${row.premium}`">
                <strong class="fig">{{ money(row.premium) }}</strong>
                <span class="label">{{ row.right.toUpperCase() }} {{ row.strike ?? DASH }}</span>
                <small>{{ row.trade_class || 'print' }}</small>
              </li>
            </ul>
            <p v-else class="missing">No additional prints for this symbol in the window.</p>
          </section>
        </div>
      </article>
    </template>
  </section>
</template>

<style scoped>
.power-alerts {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4) var(--s5);
  border: var(--hair) solid var(--rule);
  background: var(--panel);
}

.alerts-head {
  display: flex;
  justify-content: space-between;
  gap: var(--s4);
  align-items: flex-end;
}

.section-kicker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--phosphor);
}

h2 {
  margin: var(--s1) 0 0;
  color: var(--ink);
  font: 700 var(--t-title, 1.15rem) / 1.2 var(--font-display);
}

.alerts-head p {
  max-width: 72ch;
  margin: var(--s2) 0 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
  line-height: 1.45;
}

.head-meta {
  display: flex;
  gap: var(--s3);
  color: var(--ink-faint);
  white-space: nowrap;
}

.alert-filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s1);
}

.alert-filters button {
  min-height: 28px;
  padding: 2px 8px;
  color: var(--ink-dim);
  border: var(--hair) solid var(--rule);
  background: transparent;
  border-radius: 2px;
  font: 500 var(--t-tiny) / 1 var(--font-ui);
}

.alert-filters button.active {
  color: var(--void);
  background: var(--phosphor);
  border-color: var(--phosphor);
}

.empty-alerts,
.missing {
  color: var(--ink-dim);
  font-size: var(--t-small);
}

.empty-alerts strong,
.detail-head h3 {
  color: var(--ink);
}

.card-rail {
  display: flex;
  gap: var(--s2);
  overflow-x: auto;
  padding-bottom: var(--s1);
}

.alert-card {
  flex: 0 0 196px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: var(--s2) var(--s3);
  text-align: left;
  color: var(--ink);
  border: var(--hair) solid var(--rule);
  background: var(--panel-hi);
  border-radius: 2px;
}

.alert-card.active {
  background: var(--phosphor-wash);
  box-shadow: inset 2px 0 0 var(--phosphor);
}

.card-top,
.card-metrics {
  display: flex;
  width: 100%;
  justify-content: space-between;
  align-items: center;
  gap: var(--s2);
}

.symbol {
  font-size: var(--t-fig);
}

.lean-chip,
.order-chip,
.cheap {
  padding: 1px 6px;
  border: var(--hair) solid var(--rule);
  border-radius: 2px;
}

.token-long {
  color: var(--long);
}

.token-short {
  color: var(--short);
}

.call-id {
  color: var(--call);
}

.put-id {
  color: var(--put);
}

.strength {
  color: var(--ink);
}

.alert-card small {
  color: var(--ink-faint);
}

.alert-detail {
  padding: var(--s3);
  border: var(--hair) solid var(--rule);
  background: var(--surface-base, var(--panel));
}

.detail-head {
  display: flex;
  justify-content: space-between;
  gap: var(--s3);
  align-items: flex-start;
  margin-bottom: var(--s3);
}

.detail-head p {
  max-width: 70ch;
  margin: var(--s1) 0 0;
  color: var(--ink-dim);
  font-size: var(--t-small);
}

.open-setup {
  min-height: 32px;
  padding: 0 10px;
  color: var(--void);
  background: var(--phosphor);
  border: var(--hair) solid var(--phosphor);
  border-radius: 2px;
  white-space: nowrap;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1fr;
  gap: var(--s3);
}

.facts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s2);
  margin: var(--s2) 0 0;
}

.facts dt {
  color: var(--ink-faint);
  font-size: var(--t-tiny);
}

.facts dd {
  margin: 2px 0 0;
}

.alert-chart {
  display: block;
  width: 100%;
  height: 88px;
  margin-top: var(--s2);
}

.chart-fill {
  fill: color-mix(in srgb, var(--phosphor) 16%, transparent);
}

.chart-line {
  fill: none;
  stroke: var(--phosphor);
  stroke-width: 1.5;
}

.chart-mark {
  fill: var(--void);
  stroke: var(--phosphor);
  stroke-width: 1.5;
}

.day-bars {
  display: flex;
  align-items: flex-end;
  gap: var(--s2);
  height: 88px;
  margin-top: var(--s2);
}

.day-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.bar-wrap {
  display: flex;
  align-items: flex-end;
  width: 100%;
  height: 56px;
  background: var(--panel-hi);
}

.bar-wrap i {
  display: block;
  width: 100%;
  min-height: 0;
  background: var(--rule-hi, var(--rule));
}

.bar-wrap i.on {
  background: var(--phosphor);
}

.day-col small {
  color: var(--ink-faint);
}

.streak {
  margin-top: var(--s2);
  color: var(--phosphor);
}

.orders-pane ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: var(--s2) 0 0;
  padding: 0;
  list-style: none;
}

.orders-pane li {
  display: grid;
  grid-template-columns: 7rem 1fr auto;
  gap: var(--s2);
  align-items: baseline;
}

@media (max-width: 980px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .alert-card {
    flex-basis: 168px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .power-alerts {
    animation: none;
  }
}
</style>
