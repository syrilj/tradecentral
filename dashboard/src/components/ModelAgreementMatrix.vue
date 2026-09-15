<script setup lang="ts">
/**
 * ModelAgreementMatrix.vue
 *
 * 5x5 Pairwise Model Alignment Matrix & Conflict Summary.
 * Models:
 *  1. Trend (Kalman)
 *  2. Gamma Topography
 *  3. Market Structure (VR)
 *  4. Order Flow (MAD)
 *  5. Volatility Environment
 */
import { computed } from 'vue'
import type { ModelAgreement, PairwiseConflictDetail } from '@/regimeContracts'
import { DASH, num, pctFrac } from '@/format'
import Panel from '@/components/Panel.vue'

const props = withDefaults(
  defineProps<{
    agreement?: ModelAgreement | null
  }>(),
  {
    agreement: null,
  },
)

const MODEL_LABELS = ['Trend', 'Gamma', 'Structure', 'Flow', 'Vol']
const MODEL_KEYS = [
  'Trend (Kalman)',
  'Gamma Topography',
  'Market Structure (VR)',
  'Order Flow (MAD)',
  'Volatility Environment',
]

const matrix = computed(() => props.agreement?.pairwiseMatrix ?? null)
// Null payload means "not computed yet", not "0% consensus" and not an
// identity matrix -- render DASH rather than spoofing perfect/no agreement.
const consensusScore = computed<number | null>(() => props.agreement?.agreementScore ?? null)
const agreeingModels = computed(() => props.agreement?.agreeingModels ?? [])
const conflictingModels = computed(() => props.agreement?.conflictingModels ?? [])
const conflicts = computed<PairwiseConflictDetail[]>(() => props.agreement?.conflicts ?? [])

function getCellCorrelation(rowKey: string, colKey: string): number {
  if (!matrix.value || !matrix.value[rowKey]) return 0
  return matrix.value[rowKey][colKey] ?? 0
}

function getCellColorClass(val: number): string {
  if (val >= 0.5) return 'cell-align-pos'
  if (val <= -0.5) return 'cell-align-neg'
  return 'cell-align-neut'
}
</script>

<template>
  <Panel
    label="MULTI-MODEL AGREEMENT MATRIX"
    meta="5×5 ALIGNMENT"
    index="03"
    class="agreement-panel"
  >
    <div class="agreement-layout">
      <!-- Summary Header -->
      <div class="agreement-head">
        <div class="score-block">
          <span class="score-label">MODEL CONSENSUS</span>
          <span class="score-val mono">{{
            consensusScore != null ? pctFrac(consensusScore, 0) : DASH
          }}</span>
        </div>
        <div class="models-lists">
          <div v-if="agreeingModels.length > 0" class="tag-row">
            <span class="tag-hdr c-pos">AGREE:</span>
            <span v-for="m in agreeingModels" :key="m" class="m-tag tag-pos">{{ m }}</span>
          </div>
          <div v-if="conflictingModels.length > 0" class="tag-row">
            <span class="tag-hdr c-neg">CONFLICT:</span>
            <span v-for="m in conflictingModels" :key="m" class="m-tag tag-neg">{{ m }}</span>
          </div>
        </div>
      </div>

      <!-- 5x5 Heatmap Table -->
      <div class="matrix-table-wrapper">
        <table class="matrix-table">
          <thead>
            <tr>
              <th class="corner-th" />
              <th v-for="lbl in MODEL_LABELS" :key="lbl" class="col-th">{{ lbl }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(rowKey, rIdx) in MODEL_KEYS" :key="rowKey">
              <th class="row-th">{{ MODEL_LABELS[rIdx] }}</th>
              <td
                v-for="(colKey, cIdx) in MODEL_KEYS"
                :key="colKey"
                class="mat-cell mono"
                :class="[
                  getCellColorClass(getCellCorrelation(rowKey, colKey)),
                  { 'is-diag': rIdx === cIdx },
                ]"
                :title="
                  matrix
                    ? `${rowKey} vs ${colKey}: ${num(getCellCorrelation(rowKey, colKey), 2)}`
                    : `${rowKey} vs ${colKey}: unmeasured`
                "
              >
                {{
                  matrix
                    ? rIdx === cIdx
                      ? '1.0'
                      : num(getCellCorrelation(rowKey, colKey), 2)
                    : DASH
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Named Conflict Explanations -->
      <div v-if="conflicts.length > 0" class="conflicts-block">
        <div class="conflict-head">CROSS-MODEL DYNAMICS &amp; DIVERGENCES</div>
        <div v-for="c in conflicts" :key="c.conflictCode" class="conflict-item">
          <span class="conflict-badge" :class="`sev-${c.severity.toLowerCase()}`">{{
            c.severity
          }}</span>
          <span class="conflict-desc">{{ c.explanation }}</span>
        </div>
      </div>
    </div>
  </Panel>
</template>

<style scoped>
.agreement-layout {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}

.agreement-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--s3);
  padding-bottom: var(--s2);
  border-bottom: var(--hair) solid var(--rule);
  min-width: 0;
  flex-wrap: wrap;
}

.score-block {
  display: flex;
  flex-direction: column;
}

.score-label {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ink-dim);
}

.score-val {
  font-size: var(--t-fig);
  font-weight: 800;
  color: var(--ink);
}

.models-lists {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1 1 220px;
}

.tag-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.tag-hdr {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.m-tag {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: var(--r-xs);
  border: var(--hair) solid var(--rule);
}

.tag-pos {
  color: var(--call-hi);
  background: var(--call-wash);
  border-color: var(--call);
}
.tag-neg {
  color: var(--put-hi);
  background: var(--put-wash);
  border-color: var(--put);
}

.matrix-table-wrapper {
  overflow: auto;
  padding: 2px 0;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.matrix-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 0.75rem;
}

.col-th,
.row-th {
  font-family: var(--font-ui);
  color: var(--ink-dim);
  font-weight: 600;
  font-size: 0.6875rem;
  padding: 5px 4px;
  text-align: center;
  letter-spacing: 0.02em;
  overflow-wrap: anywhere;
}

.row-th {
  text-align: left;
}

.mat-cell {
  text-align: center;
  padding: 6px 4px;
  border: var(--hair) solid var(--rule);
  color: var(--ink);
  font-size: 0.75rem;
}

.mat-cell.is-diag {
  background: var(--void-lift);
  color: var(--ink-dim);
}

.cell-align-pos {
  background: var(--call-wash);
  color: var(--call-hi);
  font-weight: 700;
}

.cell-align-neg {
  background: var(--put-wash);
  color: var(--put-hi);
  font-weight: 700;
}

.cell-align-neut {
  background: var(--panel);
  color: var(--ink-soft);
}

.conflicts-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--s3);
  background: var(--void-lift);
  border: var(--hair) solid var(--rule);
  border-radius: var(--r-sm);
}

.conflict-head {
  font-family: var(--font-ui);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--warn);
}

.conflict-item {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.conflict-badge {
  font-family: var(--font-ui);
  font-size: 0.6875rem;
  font-weight: 800;
  padding: 1px 5px;
  border-radius: var(--r-xs);
  letter-spacing: 0.04em;
}

.sev-critical {
  color: var(--put-hi);
  background: var(--put-wash);
}
.sev-high {
  color: var(--warn);
  background: var(--warn-wash);
}
.sev-medium {
  color: var(--ink-dim);
  background: var(--void);
}

.conflict-desc {
  font-family: var(--font-ui);
  font-size: 0.8125rem;
  color: var(--ink-soft);
  line-height: 1.4;
}

.c-pos {
  color: var(--call-hi);
}
.c-neg {
  color: var(--put-hi);
}
.mono {
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
}
</style>
