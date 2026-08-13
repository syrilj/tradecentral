<script setup lang="ts">
import type { OptionsDirectionRead } from '@/optionsDirection'
import { num, pctFrac, DASH } from '@/format'

defineProps<{
  symbol: string
  read: OptionsDirectionRead
}>()

function signedScore(value: number | null): string {
  if (value == null) return DASH
  return `${value > 0 ? '+' : ''}${num(value, 1)}`
}

function directionArrow(state: OptionsDirectionRead['state']): string {
  if (state === 'bullish') return '↗'
  if (state === 'bearish') return '↘'
  if (state === 'mixed') return '↕'
  return '—'
}
</script>

<template>
  <section
    class="direction-brief rise"
    :class="read.state"
    :aria-label="`${symbol} options direction: ${read.headline}`"
  >
    <header class="direction-head">
      <div class="direction-mark" aria-hidden="true"><span>{{ directionArrow(read.state) }}</span></div>
      <div class="direction-copy">
        <span class="label eyebrow">{{ symbol }} · UNDERLYING DIRECTION</span>
        <div class="direction-title-line">
          <strong class="fig direction-title">{{ read.headline }}</strong>
          <span class="label confidence" :class="read.confidence">
            {{ read.confidence === 'wait' ? 'WAIT FOR EVIDENCE' : `${read.confidence} CONVICTION` }}
          </span>
        </div>
        <p>{{ read.subhead }}</p>
      </div>
      <div class="score-block">
        <div class="score-head label">
          <span>BEARISH</span>
          <strong class="fig">{{ signedScore(read.score) }}<small>/100</small></strong>
          <span>BULLISH</span>
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
        <div class="score-scale label"><span>−100</span><span>0</span><span>+100</span></div>
      </div>
    </header>

    <section class="evidence-grid" aria-label="Directional evidence">
      <div class="evidence-cell basis-cell">
        <span class="label">DIRECTION COMES FROM</span>
        <strong class="fig">{{ read.basis }}</strong>
        <small class="label">{{ read.tapeStale && !read.stale ? 'TAPE STALE' : read.stale ? 'DATED INPUTS' : 'CURRENT READ' }}</small>
      </div>
      <div class="evidence-cell">
        <span class="label">SIGNED FLOW</span>
        <strong class="fig" :class="read.signedFlow != null ? (read.signedFlow > 0 ? 'pos' : read.signedFlow < 0 ? 'neg' : '') : ''">
          {{ read.signedFlow == null ? DASH : `${read.signedFlow > 0 ? '+' : ''}${pctFrac(read.signedFlow, 1)}` }}
        </strong>
        <small class="label">{{ read.signedConfidence == null ? 'NO BUY / SELL SIDE' : `${pctFrac(read.signedConfidence, 0)} SAMPLE CONF.` }}</small>
      </div>
      <div class="evidence-cell">
        <span class="label">PRICE MOMENTUM</span>
        <strong class="fig" :class="read.momentum != null ? (read.momentum > 0 ? 'pos' : read.momentum < 0 ? 'neg' : '') : ''">
          {{ read.momentum == null ? DASH : `${read.momentum > 0 ? '+' : ''}${pctFrac(read.momentum, 2)}` }}
        </strong>
        <small class="label">{{ read.momentumFresh ? 'FRESH INPUT' : 'STALE · EXCLUDED' }}</small>
      </div>
      <div class="evidence-cell activity" :class="read.activity">
        <span class="label">CONTRACT MIX</span>
        <strong class="fig">{{ read.callPct == null ? DASH : `${read.callPct}% CALL / ${read.putPct}% PUT` }}</strong>
        <small class="label">CONTRACT IDENTITY · NOT DIRECTION</small>
      </div>
    </section>

    <footer class="direction-foot">
      <div class="driver-context">
        <span class="label">STRUCTURE CONTEXT</span>
        <div class="direction-tags">
          <span v-for="driver in read.drivers" :key="driver" class="label driver">{{ driver }}</span>
          <span v-if="!read.drivers.length" class="label driver">NO EXTRA STRUCTURE DRIVER</span>
        </div>
      </div>
      <div class="confirmation-block">
        <span class="label">{{ read.confirmationTitle }}</span>
        <p>{{ read.confirmation }}</p>
        <small class="label">Research read · not order authorization</small>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.direction-brief {
  --direction-tone: var(--ink-dim);
  display: grid;
  grid-template-columns: minmax(300px, 1.2fr) minmax(170px, 0.58fr) minmax(350px, 1.25fr) minmax(230px, 0.95fr);
  min-height: 164px;
  border: var(--hair) solid var(--border-strong);
  border-left: 3px solid var(--direction-tone);
  background: var(--panel);
}
.direction-brief.bullish { --direction-tone: var(--long, var(--call)); }
.direction-brief.bearish { --direction-tone: var(--short, var(--put)); }
.direction-brief.mixed { --direction-tone: var(--warn); }
.direction-brief.unavailable { --direction-tone: var(--ink-ghost); }

.direction-main {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr);
  min-width: 0;
  border-right: var(--hair) solid var(--rule-hi);
  background: color-mix(in srgb, var(--direction-tone) 7%, var(--void-lift));
}
.direction-index {
  display: grid;
  place-items: center;
  border-right: var(--hair) solid color-mix(in srgb, var(--direction-tone) 30%, var(--rule));
  color: var(--direction-tone);
  background: color-mix(in srgb, var(--direction-tone) 8%, var(--panel));
}
.direction-index span { font-family: var(--font-display); font-size: 2.2rem; line-height: 1; }
.direction-copy { display: flex; min-width: 0; flex-direction: column; justify-content: center; gap: var(--s2); padding: var(--s4) var(--s5); }
.eyebrow { color: var(--ink-faint); font-size: var(--t-micro); }
.direction-title-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.direction-title { color: var(--direction-tone); font-size: clamp(1.4rem, 1.8vw, 1.9rem); line-height: 1; letter-spacing: -0.04em; }
.direction-copy p { max-width: 50ch; margin: 0; color: var(--ink-soft); font-size: var(--t-small); line-height: 1.45; }
.confidence, .basis, .stale-tag, .driver {
  width: fit-content;
  padding: var(--s1) var(--s2);
  border: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
  font-size: var(--t-micro);
}
.confidence.high, .confidence.medium { color: var(--direction-tone); border-color: color-mix(in srgb, var(--direction-tone) 45%, var(--rule)); }
.confidence.low { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, var(--rule)); }
.confidence.wait { color: var(--ink-dim); }
.direction-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.basis { color: var(--direction-tone); }
.stale-tag { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, var(--rule)); }
.driver { color: var(--ink-dim); }
.direction-tags .driver { padding: 2px 6px; font-size: 10px; letter-spacing: 0.04em; }

.score-block { display: flex; min-width: 0; flex-direction: column; justify-content: center; padding: var(--s4); border-right: var(--hair) solid var(--rule-hi); background: var(--void-lift); }
.score-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s2); color: var(--ink-ghost); font-size: var(--t-micro); }
.score-head strong { color: var(--direction-tone); font-size: 1.2rem; }
.score-head small { color: var(--ink-faint); font-size: var(--t-micro); }
.score-track { position: relative; height: 12px; margin-top: 10px; overflow: hidden; border: var(--hair) solid var(--rule-hi); background: var(--panel); }
.score-zero { position: absolute; z-index: 2; top: 0; bottom: 0; left: 50%; width: 1px; background: var(--ink-dim); }
.score-fill { position: absolute; top: 2px; bottom: 2px; background: var(--direction-tone); }
.score-fill.positive { border-right: 2px solid var(--call-hi, var(--call)); }
.score-fill.negative { border-left: 2px solid var(--put-hi, var(--put)); }
.score-scale { display: flex; justify-content: space-between; margin-top: var(--s2); color: var(--ink-ghost); font-size: var(--t-micro); }

.evidence-grid { display: grid; grid-template-columns: 0.8fr 0.95fr 1.3fr; min-width: 0; border-right: var(--hair) solid var(--rule-hi); }
.evidence-cell { display: flex; min-width: 0; flex-direction: column; justify-content: center; gap: var(--s2); padding: var(--s3); border-right: var(--hair) solid var(--rule); background: var(--panel); }
.evidence-cell:last-child { border-right: 0; }
.evidence-cell > span { color: var(--ink-faint); font-size: var(--t-micro); }
.evidence-cell strong { overflow: hidden; color: var(--ink-soft); font-size: var(--t-body); line-height: 1.2; text-overflow: ellipsis; }
.evidence-cell small { overflow: visible; color: var(--ink-ghost); font-size: var(--t-micro); line-height: 1.35; white-space: normal; text-overflow: clip; }
.evidence-cell strong.pos { color: var(--long, var(--call)); }
.evidence-cell strong.neg { color: var(--short, var(--put)); }
.evidence-cell.activity.call strong { color: var(--call-hi, var(--call)); }
.evidence-cell.activity.put strong { color: var(--put-hi, var(--put)); }

.confirmation-block { display: flex; min-width: 0; flex-direction: column; justify-content: center; gap: var(--s2); padding: var(--s4); background: color-mix(in srgb, var(--direction-tone) 4%, var(--void-lift)); }
.confirmation-block > span { color: var(--direction-tone); font-size: var(--t-micro); }
.confirmation-block p { margin: 0; color: var(--ink-soft); font-size: var(--t-small); line-height: 1.45; }
.confirmation-block small { color: var(--ink-ghost); font-size: var(--t-micro); }

@media (max-width: 1120px) {
  .direction-brief { grid-template-columns: minmax(300px, 1fr) minmax(220px, 0.65fr) minmax(420px, 1.2fr); }
  .confirmation-block { grid-column: 1 / -1; min-height: 74px; border-top: var(--hair) solid var(--rule-hi); }
  .evidence-grid { border-right: 0; }
}

@media (max-width: 860px) {
  .direction-brief { grid-template-columns: 1fr; }
  .direction-main, .score-block, .evidence-grid { border-right: 0; border-bottom: var(--hair) solid var(--rule-hi); }
  .evidence-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 560px) {
  .direction-main { grid-template-columns: 42px minmax(0, 1fr); }
  .direction-index span { font-size: 1.7rem; }
  .evidence-grid { grid-template-columns: 1fr; }
  .evidence-cell { border-right: 0; border-bottom: var(--hair) solid var(--rule); }
  .evidence-cell:last-child { border-bottom: 0; }
}

/* Direction is read in three passes: side, evidence, then the next test. */
.direction-brief {
  display: flex;
  min-height: 0;
  flex-direction: column;
  border-left: 3px solid var(--direction-tone);
}
.direction-head {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) minmax(230px, .56fr);
  min-width: 0;
  border-bottom: var(--hair) solid var(--rule-hi);
  background: color-mix(in srgb, var(--direction-tone) 6%, var(--void-lift));
}
.direction-mark {
  display: grid;
  place-items: center;
  border-right: var(--hair) solid color-mix(in srgb, var(--direction-tone) 30%, var(--rule));
  color: var(--direction-tone);
  background: color-mix(in srgb, var(--direction-tone) 8%, var(--panel));
}
.direction-mark span { font-family: var(--font-display); font-size: 2.2rem; line-height: 1; }
.direction-head .direction-copy { padding: var(--s4) var(--s5); }
.direction-head .score-block {
  border-right: 0;
  border-left: var(--hair) solid var(--rule-hi);
  background: var(--void-lift);
}
.evidence-grid {
  grid-template-columns: 1.05fr repeat(3, minmax(0, 1fr));
  border-right: 0;
  border-bottom: var(--hair) solid var(--rule-hi);
}
.evidence-cell { min-height: 86px; padding: var(--s3) var(--s4); }
.evidence-cell.basis-cell { background: color-mix(in srgb, var(--direction-tone) 5%, var(--panel)); }
.evidence-cell.basis-cell strong { color: var(--direction-tone); font-size: var(--t-small); letter-spacing: .02em; }
.evidence-cell.activity strong { color: var(--ink); font-size: var(--t-small); }
.direction-foot {
  display: grid;
  grid-template-columns: minmax(270px, .8fr) minmax(0, 1.7fr);
  min-width: 0;
}
.driver-context {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: var(--s2);
  padding: var(--s3) var(--s4);
  border-right: var(--hair) solid var(--rule-hi);
  background: var(--panel);
}
.driver-context > .label { color: var(--ink-faint); font-size: var(--t-micro); }
.direction-foot .confirmation-block { min-height: 96px; }

@media (max-width: 1120px) {
  .direction-head { grid-template-columns: 58px minmax(0, 1fr); }
  .direction-head .score-block { grid-column: 1 / -1; border-top: var(--hair) solid var(--rule-hi); border-left: 0; }
  .evidence-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .direction-foot .confirmation-block { grid-column: auto; border-top: 0; }
}

@media (max-width: 700px) {
  .direction-foot { grid-template-columns: 1fr; }
  .driver-context { border-right: 0; border-bottom: var(--hair) solid var(--rule-hi); }
}

@media (max-width: 560px) {
  .direction-head { grid-template-columns: 42px minmax(0, 1fr); }
  .direction-mark span { font-size: 1.7rem; }
  .evidence-grid { grid-template-columns: 1fr; }
}
</style>
