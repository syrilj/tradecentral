<script setup lang="ts">
/**
 * The Brief — the day's best setups first, then one name read in depth.
 *
 * The top section is cross-sectional: `/api/plays` is the stack's own
 * decision funnel (market map → routed targets → directional setups → live
 * chain validation), ranked ENTER-first, refreshed while the tab is open, and
 * runnable from here when no run is persisted. It answers "what do I play
 * right now" with the exact contract, its levels and its invalidation.
 *
 * Above the setups, a Today strip reads a fixed cross-asset tape
 * (SPY, QQQ, TLT, USO, GLD, HYG) from /api/quotes. TLT is labeled
 * Treasuries and USO is labeled Oil. A missing mark stays "no print".
 * The Look at line names only prints whose absolute 1-day change is
 * at least 1 percent. It does not invent a quiet tape while quotes
 * are still loading, and it does not tell the reader to trade.
 *
 * Below the setups, the single-name read: every card answers one question
 * and links to the tab that owns the detail, so this page stays a summary
 * rather than a taller copy of the workstation. Clicking a setup, or a
 * name on the Today strip, loads its symbol here.
 *
 * The direction call comes from `/api/adaptive-signal` — the stack's own
 * multi-stream blend, under weights it derives. This page does not invent a
 * score. Dealer gamma sits in its own card because it describes range, not
 * direction, and folding it into a direction blend was the specific error
 * that made an earlier version read "leans bullish +1.00" on a name the
 * calibrated blend called neutral at +0.007.
 */
import { computed, inject, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  MACRO_TAPE_SYMBOLS,
  type AdaptiveSignalPayload,
  type MarketFlowPrint,
  type OptionsIntelligence,
  type PlaysDecision,
  type PlaysJob,
  type PlaysPayload,
  type QuotesPayload,
  type StatusPayload,
  type SupplyChainPayload,
} from '@/api'
import { useResource, type Resource } from '@/composables/useResource'
import { compact, num, signed, usd, shortDate, age, DASH } from '@/format'
import {
  humaniseError,
  prettyReason,
  rankLevels,
  readCall,
  buildLadder,
  pullMass,
  readTargets,
  sortWorries,
  type WorryItem,
} from '@/briefRead'
import type { MicrostructureRegimeSnapshot } from '@/microstructureContracts'
import PriceLadder from '@/components/PriceLadder.vue'
import LoadingState from '@/components/LoadingState.vue'
import BriefSkeletonLoader from '@/components/BriefSkeletonLoader.vue'

const TODAY_TAPE = []
