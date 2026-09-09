/** Crypto desk reads: Kalman slope-over-noise + CFTC BTC spec lean.

Kept out of the view so tests call the shipped mapper, not a reimplementation.
Missing / non-finite inputs stay missing — they never become 0.
*/

import { cotLeanFromSpecNetZ, type CotLean } from './cotLean'

export type EvidenceKind = 'measured' | 'inferred' | 'missing'
export type KalmanTrendRead = 'TREND_UP' | 'TREND_DOWN' | 'CHOP' | 'UNMEASURED'

/** Default Kalman `entry_z`. |slope / noise| at or beyond this is a trend. */
export const KALMAN_TREND_Z_CUTOFF = 1.0

export const CRYPTO_KALMAN_SOURCE = 'Kalman constant-velocity · slope / noise'
export const CRYPTO_COT_SOURCE = 'CFTC COT · Bitcoin futures spec-net z'

/** Finite number, or null. NaN / ±Infinity / undefined never collapse to 0. */
export function finiteOrNull(value: number | null | undefined): number | null {
  if (value == null) return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return n
}

export function kalmanTrendFromSlopeOverNoise(z: number | null | undefined): KalmanTrendRead {
  const v = finiteOrNull(z)
  if (v == null) return 'UNMEASURED'
  if (v >= KALMAN_TREND_Z_CUTOFF) return 'TREND_UP'
  if (v <= -KALMAN_TREND_Z_CUTOFF) return 'TREND_DOWN'
  return 'CHOP'
}

export interface CryptoReadInput {
  kalmanSlopeOverNoise?: number | null
  cotSpecNetZ?: number | null
}

export interface CryptoEvidence<T> {
  value: number | null
  read: T
  kind: EvidenceKind
  source: string
}

export interface CryptoSpotRead {
  kalman: CryptoEvidence<KalmanTrendRead>
  cot: CryptoEvidence<CotLean>
  combined: {
    lean: CotLean
    kind: EvidenceKind
    label: CotLean
  }
}

function kalmanAsLean(read: KalmanTrendRead): CotLean {
  if (read === 'TREND_UP') return 'LONG'
  if (read === 'TREND_DOWN') return 'SHORT'
  if (read === 'CHOP') return 'BALANCED'
  return 'UNKNOWN'
}

function combinedLean(kalman: KalmanTrendRead, cot: CotLean): CotLean {
  const fromKalman = kalmanAsLean(kalman)
  if (cot === 'UNKNOWN') return fromKalman
  if (fromKalman === 'UNKNOWN') return cot
  if (cot === fromKalman) return cot
  if (kalman === 'CHOP') return cot
  if (cot === 'BALANCED') return fromKalman
  return 'BALANCED'
}

/** Map Kalman z + COT spec-net z onto labeled, source-tagged reads. */
export function cryptoSpotRead(input: CryptoReadInput): CryptoSpotRead {
  const kalmanZ = finiteOrNull(input.kalmanSlopeOverNoise)
  const cotZ = finiteOrNull(input.cotSpecNetZ)
  const kalmanRead = kalmanTrendFromSlopeOverNoise(kalmanZ)
  const cotLean = cotLeanFromSpecNetZ(cotZ)
  const kalmanKind: EvidenceKind = kalmanZ == null ? 'missing' : 'measured'
  const cotKind: EvidenceKind = cotZ == null ? 'missing' : 'measured'
  const combinedKind: EvidenceKind =
    kalmanKind === 'missing' && cotKind === 'missing' ? 'missing' : 'inferred'
  const lean = combinedLean(kalmanRead, cotLean)
  return {
    kalman: {
      value: kalmanZ,
      read: kalmanRead,
      kind: kalmanKind,
      source: CRYPTO_KALMAN_SOURCE,
    },
    cot: {
      value: cotZ,
      read: cotLean,
      kind: cotKind,
      source: CRYPTO_COT_SOURCE,
    },
    combined: {
      lean,
      kind: combinedKind,
      label: lean,
    },
  }
}

export function kalmanTrendLabel(read: KalmanTrendRead): string {
  if (read === 'TREND_UP') return 'Trend up'
  if (read === 'TREND_DOWN') return 'Trend down'
  if (read === 'CHOP') return 'Chop'
  return 'Unmeasured'
}
