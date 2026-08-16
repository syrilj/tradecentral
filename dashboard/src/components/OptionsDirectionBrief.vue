<script setup lang="ts">
import type { OptionsDirectionRead } from '@/optionsDirection'
import { num, pctFrac } from '@/format'

defineProps<{
  symbol: string
  read: OptionsDirectionRead
}>()

function signedScore(value: number | null): string {
  if (value == null) return '+0.0'
  return `${value > 0 ? '+' : ''}${num(value, 1)}`
}

function directionArrow(state: OptionsDirectionRead['state']): string {
  if (state === 'bullish') return '↗'
  if (state === 'bearish') return '↘'
  if (state === 'mixed') return '↕'
  return '•'
}
</script>

<template>
  <section
    class="direction-brief rise"
    :class="read.state"
    :aria-label="`${symbol} options direction: ${read.headline}`"
    :title="read.confirmation"
  >
    <div class="direction-mark" aria-hidden="true"><span>{{ directionArrow(read.state) }}</span></div>
    <div class="direction-copy">
      <span class="label eyebrow">{{ symbol }} · UNDERLYING DIRECTION</span>
      <div class="direction-title-line">
        <strong class="fig direction-title">{{ read.headline }}</strong>
        <span class="label confidence" :class="read.confidence">
          {{ read.confidence === 'wait' ? 'WAIT FOR EVIDENCE' : `${read.confidence} CONVICTION` }}
        </span>
      </div>
    </div>

    <div class="score-block">
      <div class="score-head label">
        <span class="score-side-label bear">BEARISH</span>
        <strong class="fig">{{ signedScore(read.score) }}<small>/100</small></strong>
        <span class="score-side-label bull">BULLISH</span>
      </div>
      <div class="score-track" aria-label="Directional squeeze score from bearish to bullish">
        <i class="score-zero" />
        <i
          v-if="read.score != null"
          class="score-fill"
          :class="read.score >= 0 ? 'positive' : 'negative'"
          :style="read.score >= 0
            ? { left: '50%', width: `${Math.min(50, Math.abs(read.score) / 2)}%` }
            : { left: `${50 - Math.min(50, Math.abs(read.score) / 2)}%`, width: `${Math.min(50, Math.abs(read.score) / 2)}%` }"
        />
      </div>
    </div>

    <div class="evidence-strip" aria-label="Directional evidence">
      <div class="evidence-cell basis-cell">
        <span class="label">DIRECTION COMES FROM</span>
        <strong class="fig">{{ read.basis }}</strong>
      </div>
      <div class="evidence-cell">
        <span class="label">SIGNED FLOW</span>
        <strong class="fig" :class="read.signedFlow != null ? (read.signedFlow > 0 ? 'pos' : read.signedFlow < 0 ? 'neg' : '') : ''">
          {{ read.signedFlow == null ? '+0.0%' : `${read.signedFlow > 0 ? '+' : ''}${pctFrac(read.signedFlow, 1)}` }}
        </strong>
        <small class="label">{{ read.signedConfidence == null ? 'NO BUY / SELL SIDE' : `${pctFrac(read.signedConfidence, 0)} CONF.` }}</small>
      </div>
      <div class="evidence-cell">
        <span class="label">PRICE MOMENTUM</span>
        <strong class="fig" :class="read.momentum != null ? (read.momentum > 0 ? 'pos' : read.momentum < 0 ? 'neg' : '') : ''">
          {{ read.momentum == null ? '+0.00%' : `${read.momentum > 0 ? '+' : ''}${pctFrac(read.momentum, 2)}` }}
        </strong>
        <small class="label">{{ read.momentumFresh ? 'FRESH' : 'STALE · EXCLUDED' }}</small>
      </div>
      <div class="evidence-cell activity" :class="read.activity">
        <span class="label">CONTRACT MIX</span>
        <strong class="fig">{{ read.callPct == null ? '0% C / 0% P' : `${read.callPct}% C / ${read.putPct}% P` }}</strong>
        <small class="label">NOT DIRECTION</small>
      </div>
    </div>
  </section>
</template>

<style scoped>
.direction-brief {
  --direction-tone: var(--ink-dim);
  display: grid;
  grid-template-columns: 40px minmax(160px, 0.9fr) minmax(140px, 0.55fr) minmax(0, 2.2fr);
  align-items: stretch;
  min-height: 60px;
  border: var(--hair) solid var(--border-strong);
  border-left: 3px solid var(--direction-tone);
  background: var(--panel);
}
.direction-brief.bullish { --direction-tone: var(--long); }
.direction-brief.bearish { --direction-tone: var(--short); }
.direction-brief.mixed { --direction-tone: var(--warn); }
.direction-brief.unavailable { --direction-tone: var(--ink-ghost); }

.direction-mark {
  display: grid;
  place-items: center;
  border-right: var(--hair) solid color-mix(in srgb, var(--direction-tone) 30%, var(--rule));
  color: var(--direction-tone);
  background: var(--panel);
}
.direction-mark span { font-family: var(--font-display); font-size: 1.35rem; line-height: 1; }

.direction-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 6px 10px;
  background: var(--void-lift);
}
.eyebrow { color: var(--ink-faint); font-size: var(--t-micro); }
.direction-title-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.direction-title { color: var(--direction-tone); font-size: 1.05rem; line-height: 1.1; letter-spacing: -0.03em; }
.confidence {
  width: fit-content;
  padding: 1px 6px;
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  font-size: var(--t-micro);
}
.confidence.high, .confidence.medium { color: var(--direction-tone); border-color: color-mix(in srgb, var(--direction-tone) 45%, var(--rule)); }
.confidence.low { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, var(--rule)); }
.confidence.wait { color: var(--ink-dim); }

.score-block {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 6px 10px;
  border-left: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
}
.score-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s2); color: var(--ink-ghost); font-size: var(--t-micro); }
.score-head strong { color: var(--direction-tone); font-size: 0.95rem; }
.score-head small { color: var(--ink-faint); font-size: var(--t-micro); }
.score-side-label.bull { color: var(--long); font-weight: 600; }
.score-side-label.bear { color: var(--short); font-weight: 600; }
.score-track { position: relative; height: 8px; overflow: hidden; border: var(--hair) solid var(--rule-hi); background: var(--panel); }
.score-zero { position: absolute; z-index: 2; top: 0; bottom: 0; left: 50%; width: 1px; background: var(--ink-dim); }
.score-fill { position: absolute; top: 1px; bottom: 1px; background: var(--direction-tone); }
.score-fill.positive { border-right: 2px solid var(--long); }
.score-fill.negative { border-left: 2px solid var(--short); }

.evidence-strip {
  display: grid;
  grid-template-columns: 1.15fr repeat(3, minmax(0, 1fr));
  min-width: 0;
  border-left: var(--hair) solid var(--rule-hi);
}
.evidence-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: 1px;
  padding: 4px 8px;
  border-right: var(--hair) solid var(--rule);
  background: var(--panel);
}
.evidence-cell:last-child { border-right: 0; }
.evidence-cell > span { color: var(--ink-faint); font-size: 9px; }
.evidence-cell strong { overflow: hidden; color: var(--ink-soft); font-size: 11px; line-height: 1.15; text-overflow: ellipsis; white-space: nowrap; }
.evidence-cell small { overflow: hidden; color: var(--ink-ghost); font-size: 9px; line-height: 1.2; white-space: nowrap; text-overflow: ellipsis; }
.evidence-cell strong.pos { color: var(--long); }
.evidence-cell strong.neg { color: var(--short); }
.evidence-cell.activity.call strong { color: var(--call-hi, var(--call)); }
.evidence-cell.activity.put strong { color: var(--put-hi, var(--put)); }
.evidence-cell.basis-cell { background: var(--panel); }
.evidence-cell.basis-cell strong { color: var(--direction-tone); letter-spacing: .02em; }

@media (max-width: 1120px) {
  .direction-brief {
    grid-template-columns: 36px minmax(0, 1fr) minmax(140px, 0.6fr);
    max-height: none;
  }
  .evidence-strip { grid-column: 1 / -1; border-left: 0; border-top: var(--hair) solid var(--rule-hi); }
}

@media (max-width: 700px) {
  .direction-brief { grid-template-columns: 36px minmax(0, 1fr); }
  .score-block { grid-column: 1 / -1; border-left: 0; border-top: var(--hair) solid var(--rule-hi); }
  .evidence-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 560px) {
  .evidence-strip { grid-template-columns: 1fr; }
  .evidence-cell { border-right: 0; border-bottom: var(--hair) solid var(--rule); }
  .evidence-cell:last-child { border-bottom: 0; }
}
</style>
