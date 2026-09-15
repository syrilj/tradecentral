<script setup lang="ts">
import { computed } from 'vue'
import type { ExecutionGatePayload } from '@/microstructureContracts'
import { num, DASH } from '@/format'

const props = withDefaults(
  defineProps<{
    gate: ExecutionGatePayload | null
  }>(),
  { gate: null },
)

const g = computed(() => props.gate)

/** Operator-facing names for the session phases the backend emits. */
const PHASE_TITLES: Record<string, string> = {
  pre_market: 'Pre-market',
  opening_auction: 'Opening auction',
  morning_initiative: 'Morning initiative',
  lunch_consolidation: 'Lunch consolidation',
  afternoon_acceleration: 'Afternoon acceleration',
  liquidation: 'Liquidation',
  post_market: 'Post-market',
}

const SETUP_TITLES: Record<string, string> = {
  mean_reversion: 'Mean reversion',
  expansion: 'Expansion',
  reflexive_squeeze: 'Reflexive squeeze',
}

const phaseTitle = computed(() => {
  const p = g.value?.session.phase
  return p ? (PHASE_TITLES[p] ?? p) : DASH
})

const mayEnter = computed(() => g.value?.session.may_enter === true)
const mustBeFlat = computed(() => g.value?.session.must_be_flat === true)

const setups = computed(() =>
  (g.value?.session.permitted_setups ?? []).map((s) => SETUP_TITLES[s] ?? s),
)

const ib = computed(() => g.value?.initial_balance ?? null)
const ibMeasured = computed(() => ib.value?.measurable === true)

const contract = computed(() => g.value?.contract ?? null)
const contractRouted = computed(() => contract.value?.measurable === true)

/** Where spot sits against the opening range, once both are real numbers. */
const ibLocation = computed(() => {
  const spot = g.value?.spot
  const high = ib.value?.high
  const low = ib.value?.low
  if (spot == null || high == null || low == null) return null
  if (spot > high) return 'above'
  if (spot < low) return 'below'
  return 'inside'
})

const expiryLabel = computed(() => {
  const p = g.value?.expiry_policy
  if (!p) return DASH
  return p.min_dte === p.max_dte ? `${p.min_dte} DTE` : `${p.min_dte}–${p.max_dte} DTE`
})
</script>

<template>
  <div class="gate-card">
    <div v-if="!g" class="gate-empty">No execution gate read.</div>

    <template v-else>
      <!-- Session clock. The permission verdict leads, because every other
           panel on this card is moot when the clock says no. -->
      <div class="gate-row" :class="mayEnter ? 'ok' : 'blocked'">
        <div class="gate-head">
          <span class="gate-label">SESSION</span>
          <span class="gate-pill" :class="mayEnter ? 'pos' : 'neg'">
            {{ mayEnter ? 'ENTRIES OPEN' : 'NO ENTRIES' }}
          </span>
        </div>
        <div class="gate-val">{{ phaseTitle }}</div>
        <div class="gate-sub">{{ g.session.reason }}</div>
        <div class="gate-sub muted">{{ g.session.exchange_time }}</div>
        <div v-if="mustBeFlat" class="gate-alarm">
          Past 15:45 — all open options must already be closed.
        </div>
        <div v-if="setups.length" class="gate-chips">
          <span v-for="s in setups" :key="s" class="chip">{{ s }}</span>
        </div>
      </div>

      <!-- Expiry policy -->
      <div class="gate-row">
        <div class="gate-head">
          <span class="gate-label">EXPIRY POLICY</span>
          <span class="gate-pill" :class="g.expiry_policy.zero_dte_permitted ? 'pos' : 'neu'">
            {{ g.expiry_policy.zero_dte_permitted ? '0DTE OK' : 'NO 0DTE' }}
          </span>
        </div>
        <div class="gate-val">{{ expiryLabel }}</div>
        <div class="gate-sub">{{ g.expiry_policy.rationale }}</div>
      </div>

      <!-- Initial Balance. Unmeasurable before 09:45 and on a late feed;
           both are normal states, so the reason is shown rather than a
           zero-width range that would read as a real, very tight IB. -->
      <div class="gate-row">
        <div class="gate-head">
          <span class="gate-label">INITIAL BALANCE · 09:30–09:45</span>
          <span v-if="ibMeasured && ibLocation" class="gate-pill" :class="ibLocation === 'inside' ? 'neu' : 'pos'">
            SPOT {{ ibLocation.toUpperCase() }}
          </span>
        </div>
        <template v-if="ibMeasured">
          <div class="gate-val font-mono">
            {{ num(ib!.low, 2) }} – {{ num(ib!.high, 2) }}
          </div>
          <div class="gate-sub">
            Width {{ num(ib!.width, 2) }} · {{ ib!.bar_count }} bars · {{ ib!.session_date }}
          </div>
        </template>
        <template v-else>
          <div class="gate-val">{{ DASH }}</div>
          <div class="gate-sub">{{ ib?.reason ?? 'Not measured.' }}</div>
        </template>
      </div>

      <!-- Routed contract -->
      <div class="gate-row">
        <div class="gate-head">
          <span class="gate-label">ROUTED CONTRACT · 0.35–0.50 Δ</span>
          <span v-if="contractRouted" class="gate-pill pos">ROUTED</span>
        </div>
        <template v-if="contractRouted">
          <div class="gate-val font-mono">
            {{ num(contract!.strike, 2) }} {{ contract!.right?.toUpperCase() }} · {{ contract!.expiry }}
          </div>
          <div class="gate-sub">
            Δ {{ num(contract!.delta, 3) }} · {{ contract!.dte }} DTE ·
            {{ contract!.considered }} contracts considered
          </div>
          <div v-if="contract!.spread?.measurable" class="gate-sub">
            Spread {{ num(contract!.spread!.ratio_pct, 2) }}% against a
            {{ num(contract!.spread!.cap_pct, 1) }}% cap
            <span :class="contract!.spread!.passes ? 'ok-text' : 'bad-text'">
              — {{ contract!.spread!.passes ? 'crossable' : 'too wide' }}
            </span>
          </div>
          <div
            v-for="w in contract!.warnings"
            :key="w"
            class="gate-warn"
          >
            {{ w }}
          </div>
        </template>
        <template v-else>
          <div class="gate-val">{{ DASH }}</div>
          <div class="gate-sub">{{ contract?.reason ?? 'No chain routed.' }}</div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.gate-card {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--s2);
}
.gate-empty {
  color: var(--ink-faint);
  font-size: var(--t-micro);
  padding: var(--s3);
}
.gate-row {
  border: var(--hair) solid var(--rule-faint);
  border-radius: var(--r-sm);
  padding: var(--s2) var(--s3);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.gate-row.ok {
  border-color: var(--long-dim, var(--long));
}
.gate-row.blocked {
  border-color: var(--short-dim, var(--short));
}
.gate-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s2);
}
.gate-label {
  font-size: var(--t-nano);
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}
.gate-pill {
  font-size: var(--t-nano);
  letter-spacing: 0.05em;
  padding: 1px var(--s1);
  border-radius: var(--r-sm);
  white-space: nowrap;
}
.gate-pill.pos {
  background: var(--call-wash);
  color: var(--call-hi);
}
.gate-pill.neg {
  background: var(--put-wash);
  color: var(--put-hi);
}
.gate-pill.neu {
  background: var(--panel-hi);
  color: var(--ink-faint);
}
.gate-val {
  font-size: 1.125rem;
  line-height: 1.2;
  color: var(--ink);
}
.gate-sub {
  font-size: var(--t-micro);
  color: var(--ink-dim);
  line-height: 1.35;
}
.gate-sub.muted {
  color: var(--ink-faint);
}
.gate-alarm {
  font-size: var(--t-micro);
  color: var(--put-hi);
}
.gate-warn {
  font-size: var(--t-nano);
  color: var(--warn);
  line-height: 1.35;
}
.ok-text {
  color: var(--call-hi);
}
.bad-text {
  color: var(--put-hi);
}
.gate-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s1);
  margin-top: 1px;
}
.chip {
  font-size: var(--t-nano);
  padding: 1px var(--s1);
  border-radius: var(--r-sm);
  border: var(--hair) solid var(--rule-faint);
  color: var(--ink-dim);
}
</style>
