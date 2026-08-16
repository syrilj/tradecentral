/** Spec-net z → desk lean for CFTC COT books. Shared by Pulse and the strip. */

export type CotLean = 'LONG' | 'SHORT' | 'BALANCED' | 'UNKNOWN'

/** Same cutoffs as `cot_lean_from_spec_net_z` in tools/sentiment_anomalies.py. */
export const COT_LEAN_Z_CUTOFF = 0.5

export function cotLeanFromSpecNetZ(z: number | null | undefined): CotLean {
  if (z == null || !Number.isFinite(Number(z))) return 'UNKNOWN'
  const value = Number(z)
  if (value >= COT_LEAN_Z_CUTOFF) return 'LONG'
  if (value <= -COT_LEAN_Z_CUTOFF) return 'SHORT'
  return 'BALANCED'
}

export function cotLeanFromBias(bias: string | null | undefined): CotLean {
  const key = String(bias ?? '').toUpperCase()
  if (key.includes('LONG')) return 'LONG'
  if (key.includes('SHORT')) return 'SHORT'
  if (key.includes('BALANCED')) return 'BALANCED'
  return 'UNKNOWN'
}

export function cotLeanTone(lean: CotLean): 'pos' | 'neg' | 'flat' {
  if (lean === 'LONG') return 'pos'
  if (lean === 'SHORT') return 'neg'
  return 'flat'
}
