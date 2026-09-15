"""Layer 3 Market Regime Reconciliation & Calibrated Aggregation Engine.

Theoretical Foundations:
- Deterministic Aggregation: Unambiguous hierarchical decision ladder combining
  Trend (Kalman), Volatility (252d percentile), Market Structure (Lo-MacKinlay VR / OU),
  Transition Risk (CUSUM / BOCPD / Flip), and Flow Context into the 7 primary regime states.
- Probability Simplex: Temperature-scaled evidence softmax guaranteeing strictly
  p_bull + p_bear + p_neutral = 1.0000 with dynamic entropy expansion under hazard.
- Calibrated Multi-Factor Confidence: Strictly multiplicative zero-trust formulation
  C = Q_data * A_models * D_boundary * S_persistence * (1.0 - 0.5 * T_risk) in [0.0, 1.0].
- 5x5 Multi-Model Agreement Matrix & Consensus Metric.
- Fail-Closed Safety Guarantees: Forces UNCERTAIN_TRANSITIONAL on boundary proximity,
  transition hazard spikes, severe model conflict, or low consensus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from edge.research.bocpd import BocpdResult, ConstantHazard, GaussianVarianceModel, bocpd
from edge.research.kalman_trend import KalmanTrendResult, kalman_trend
from edge.research.regime_features import (
    RegimeFeatureConfig,
    build_layer1_regime_features,
    compute_dollar_gex_profile,
    compute_log_returns,
)
from edge.research.regimes import (
    MarketStructureResult,
    TransitionRiskResult,
    VolatilityRegimeResult,
    compute_cusum_transition_risk,
    compute_market_structure,
    compute_ou_half_life,
    compute_rolling_volatility_regime,
    compute_variance_ratio,
)

# ---------------------------------------------------------------------------
# Enums & Contracts
# ---------------------------------------------------------------------------


class PrimaryRegime(str, Enum):
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    COMPRESSION_RANGE = "COMPRESSION_RANGE"
    MEAN_REVERTING = "MEAN_REVERTING"
    VOL_EXPANSION_BREAKOUT = "VOL_EXPANSION_BREAKOUT"
    UNCERTAIN_TRANSITIONAL = "UNCERTAIN_TRANSITIONAL"
    UNMEASURABLE = "UNMEASURABLE"


class VolatilityState(str, Enum):
    COMPRESSION_LOW = "COMPRESSION_LOW"
    NORMAL_MEDIUM = "NORMAL_MEDIUM"
    ELEVATED_HIGH = "ELEVATED_HIGH"
    VOLATILITY_SHOCK = "VOLATILITY_SHOCK"


class MarketStructure(str, Enum):
    TRENDING = "TRENDING"
    MEAN_REVERTING = "MEAN_REVERTING"
    RANGE_BOUND = "RANGE_BOUND"


class FlowContext(str, Enum):
    INSTITUTIONAL_ACCUMULATION = "INSTITUTIONAL_ACCUMULATION"
    INSTITUTIONAL_DISTRIBUTION = "INSTITUTIONAL_DISTRIBUTION"
    ABSORPTION_CHURN = "ABSORPTION_CHURN"
    BALANCED_FLOW = "BALANCED_FLOW"


@dataclass(frozen=True)
class RegimeProbabilities:
    """Strictly normalized probability distribution (sum = 1.0000)."""

    bullish: float
    bearish: float
    neutral: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "bullish": self.bullish,
            "bearish": self.bearish,
            "neutral": self.neutral,
        }


@dataclass(frozen=True)
class ModelPosture:
    """Standardized directional posture for one Layer 2 model."""

    model_name: str
    continuous_score: float  # u_k in [-1.0, 1.0]
    discrete_stance: int  # -1, 0, or +1
    raw_metric_name: str
    raw_metric_value: float
    description: str


@dataclass(frozen=True)
class PairwiseConflict:
    """Specific named conflict between two Layer 2 models."""

    conflict_code: str  # e.g., 'CONF_GAMMA_TREND'
    model_a: str
    model_b: str
    correlation: float  # M_ij in [-1.0, 1.0]
    severity: str  # 'HIGH' | 'CRITICAL' | 'MEDIUM'
    explanation: str


@dataclass(frozen=True)
class ModelAgreement:
    """5x5 Multi-Model Agreement Matrix and Consensus Score."""

    overall_agreement: float
    agreeing_models: List[str]
    conflicting_models: List[str]
    divergence_summary: Optional[str]
    pairwise_matrix: Optional[Dict[str, Dict[str, float]]] = None
    conflicts: List[PairwiseConflict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_agreement": self.overall_agreement,
            "agreeing_models": list(self.agreeing_models),
            "conflicting_models": list(self.conflicting_models),
            "divergence_summary": self.divergence_summary,
            "pairwise_matrix": self.pairwise_matrix,
            "conflicts": [
                {
                    "conflict_code": c.conflict_code,
                    "model_a": c.model_a,
                    "model_b": c.model_b,
                    "correlation": c.correlation,
                    "severity": c.severity,
                    "explanation": c.explanation,
                }
                for c in self.conflicts
            ],
        }


@dataclass(frozen=True)
class FeatureDriver:
    """Ranked feature attribution contribution."""

    feature: str
    value: float
    contribution: float
    description: str


@dataclass(frozen=True)
class DynamicExplainability:
    """Dynamic explainability narrative without canned static templates."""

    summary_text: str
    leading_drivers: List[Dict[str, Any]]
    transition_alert: Optional[str]
    headline: Optional[str] = None
    risk_factors: List[str] = field(default_factory=list)
    uncertainty_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary_text": self.summary_text,
            "leading_drivers": self.leading_drivers,
            "transition_alert": self.transition_alert,
            "headline": self.headline,
            "risk_factors": list(self.risk_factors),
            "uncertainty_sources": list(self.uncertainty_sources),
        }


@dataclass(frozen=True)
class StructuralLevels:
    """Options and session structural boundaries."""

    call_wall: Optional[float]
    put_wall: Optional[float]
    gamma_flip: Optional[float]
    session_vwap: Optional[float]

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "gamma_flip": self.gamma_flip,
            "session_vwap": self.session_vwap,
        }


@dataclass(frozen=True)
class QualityMetrics:
    """Data completeness and measurement validity metrics."""

    measurable: bool
    data_completeness: float
    reason: Optional[str] = None
    missing_lenses: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "measurable": self.measurable,
            "data_completeness": self.data_completeness,
            "reason": self.reason,
            "missing_lenses": list(self.missing_lenses),
        }


@dataclass(frozen=True)
class ConfidenceComponents:
    """Detailed multi-factor confidence breakdown."""

    q_data: float
    q_bars: float
    q_chain: float
    q_freshness: float
    a_models: float
    d_boundary: float
    d_flip: float
    d_trend: float
    s_persistence: float
    tenure_bars: int
    whipsaw_penalty: float
    t_risk: float
    hazard_multiplier: float
    composite_confidence: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "q_data": self.q_data,
            "q_bars": self.q_bars,
            "q_chain": self.q_chain,
            "q_freshness": self.q_freshness,
            "a_models": self.a_models,
            "d_boundary": self.d_boundary,
            "d_flip": self.d_flip,
            "d_trend": self.d_trend,
            "s_persistence": self.s_persistence,
            "tenure_bars": float(self.tenure_bars),
            "whipsaw_penalty": self.whipsaw_penalty,
            "t_risk": self.t_risk,
            "hazard_multiplier": self.hazard_multiplier,
            "composite_confidence": self.composite_confidence,
        }


@dataclass(frozen=True)
class UnifiedMarketState:
    """Unified Layer 3 Multi-Dimensional Market State."""

    symbol: str
    spot: Optional[float]
    asof: str
    primary_regime: PrimaryRegime
    confidence: float
    volatility_state: VolatilityState
    market_structure: MarketStructure
    flow_context: FlowContext
    transition_risk: float
    probabilities: RegimeProbabilities
    model_agreement: ModelAgreement
    explainability: DynamicExplainability
    levels: StructuralLevels
    quality: QualityMetrics
    confidence_components: Optional[ConfidenceComponents] = None
    pillar_metrics: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "asof": self.asof,
            "primary_regime": self.primary_regime.value,
            "confidence": self.confidence,
            "volatility_state": self.volatility_state.value,
            "market_structure": self.market_structure.value,
            "flow_context": self.flow_context.value,
            "transition_risk": self.transition_risk,
            "probabilities": self.probabilities.to_dict(),
            "model_agreement": self.model_agreement.to_dict(),
            "explainability": self.explainability.to_dict(),
            "levels": self.levels.to_dict(),
            "quality": self.quality.to_dict(),
            "confidence_components": (
                self.confidence_components.to_dict() if self.confidence_components else None
            ),
            "pillar_metrics": self.pillar_metrics,
        }


# ---------------------------------------------------------------------------
# Mathematical Helper Functions
# ---------------------------------------------------------------------------


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp float to closed interval [lo, hi]."""
    if not math.isfinite(val):
        return lo
    return max(lo, min(hi, float(val)))


def compute_multi_model_postures(
    kalman_z: float,
    net_gex_usd: Optional[float],
    gex_scale_usd: Optional[float],
    delta_flip: Optional[float],
    variance_ratio: float,
    flow_mad_z: float,
    vol_percentile: float,
) -> List[ModelPosture]:
    """Compute continuous directional postures u_k in [-1.0, 1.0] across 5 Layer 2 models."""
    # 1. Trend Model: u_1 = tanh(z_v / 1.5)
    u_trend = math.tanh(kalman_z / 1.5)
    trend_stance = 1 if u_trend > 0.3 else (-1 if u_trend < -0.3 else 0)
    p_trend = ModelPosture(
        model_name="Trend (Kalman)",
        continuous_score=round(u_trend, 4),
        discrete_stance=trend_stance,
        raw_metric_name="kalman_zscore",
        raw_metric_value=round(kalman_z, 4),
        description=f"Kalman velocity z-score: {kalman_z:+.2f}z",
    )

    # 2. Gamma Model: u_2
    if net_gex_usd is not None and gex_scale_usd is not None and gex_scale_usd > 0:
        d_flip_val = abs(delta_flip) if delta_flip is not None else 0.01
        sign_gex = 1.0 if net_gex_usd > 0 else (-1.0 if net_gex_usd < 0 else 0.0)
        norm_mag = math.tanh(abs(net_gex_usd) / gex_scale_usd)
        norm_flip = math.tanh(d_flip_val / 0.01)
        u_gamma = sign_gex * norm_mag * norm_flip
        gamma_stance = 1 if u_gamma > 0.3 else (-1 if u_gamma < -0.3 else 0)
        p_gamma = ModelPosture(
            model_name="Gamma Topography",
            continuous_score=round(u_gamma, 4),
            discrete_stance=gamma_stance,
            raw_metric_name="net_gex_m",
            raw_metric_value=round(net_gex_usd / 1e6, 4),
            description=f"Net GEX: ${net_gex_usd / 1e6:+.2f}M with delta_flip: {d_flip_val * 100:.2f}%",
        )
    else:
        # Options lens unmeasured
        u_gamma = 0.0
        p_gamma = ModelPosture(
            model_name="Gamma Topography",
            continuous_score=0.0,
            discrete_stance=0,
            raw_metric_name="net_gex_m",
            raw_metric_value=0.0,
            description="Gamma profile unmeasured or open interest absent",
        )

    # 3. Market Structure: u_3 = tanh((VR(5) - 1.0) / 0.25) * sign(u_trend)
    vr_dev = (variance_ratio - 1.0) / 0.25
    trend_sign = 1.0 if u_trend >= 0 else -1.0
    u_struct = math.tanh(vr_dev) * trend_sign
    struct_stance = 1 if u_struct > 0.3 else (-1 if u_struct < -0.3 else 0)
    p_struct = ModelPosture(
        model_name="Market Structure (VR)",
        continuous_score=round(u_struct, 4),
        discrete_stance=struct_stance,
        raw_metric_name="variance_ratio_5",
        raw_metric_value=round(variance_ratio, 4),
        description=f"Variance Ratio VR(5): {variance_ratio:.2f}",
    )

    # 4. Order Flow: u_4 = tanh(z_flow / 2.0)
    u_flow = math.tanh(flow_mad_z / 2.0)
    flow_stance = 1 if u_flow > 0.3 else (-1 if u_flow < -0.3 else 0)
    p_flow = ModelPosture(
        model_name="Order Flow (MAD)",
        continuous_score=round(u_flow, 4),
        discrete_stance=flow_stance,
        raw_metric_name="flow_mad_z",
        raw_metric_value=round(flow_mad_z, 4),
        description=f"Signed flow proxy MAD z-score: {flow_mad_z:+.2f}z",
    )

    # 5. Volatility Tilt: u_5 = (1.0 - 2.0 * Pct_rv) * sign(u_trend)
    vol_tilt = (1.0 - 2.0 * _clamp(vol_percentile, 0.0, 1.0)) * trend_sign
    vol_stance = 1 if vol_tilt > 0.3 else (-1 if vol_tilt < -0.3 else 0)
    p_vol = ModelPosture(
        model_name="Volatility Environment",
        continuous_score=round(vol_tilt, 4),
        discrete_stance=vol_stance,
        raw_metric_name="volatility_percentile",
        raw_metric_value=round(vol_percentile, 4),
        description=f"252d Realized Vol Percentile: {vol_percentile * 100:.1f}%",
    )

    return [p_trend, p_gamma, p_struct, p_flow, p_vol]


def build_agreement_matrix(
    postures: Sequence[float | ModelPosture],
    model_names: Optional[Sequence[str]] = None,
    vol_state: Optional[str] = None,
    variance_ratio: Optional[float] = None,
    ou_half_life: Optional[float] = None,
) -> Tuple[np.ndarray, float, List[PairwiseConflict]]:
    """Build NxN symmetric pairwise agreement matrix M_ij and detect named conflicts."""
    u_vals: List[float] = []
    names: List[str] = []

    if postures and isinstance(postures[0], ModelPosture):
        for p in postures:  # type: ignore
            u_vals.append(float(p.continuous_score))
            names.append(str(p.model_name))
    else:
        u_vals = [float(x) for x in postures]
        default_names = [
            "Trend (Kalman)",
            "Gamma Topography",
            "Market Structure (VR)",
            "Order Flow (MAD)",
            "Volatility Environment",
        ]
        names = list(model_names) if model_names is not None else default_names[: len(u_vals)]

    n = len(u_vals)
    if n == 0:
        return np.zeros((0, 0)), 0.0, []

    mat = np.ones((n, n), dtype=float)
    pair_sum = 0.0
    pair_count = 0

    conflicts: List[PairwiseConflict] = []

    for i in range(n):
        for j in range(i + 1, n):
            m_ij = u_vals[i] * u_vals[j]
            mat[i, j] = m_ij
            mat[j, i] = m_ij
            # Rescale M_ij from [-1, 1] to [0, 1]
            pair_sum += (m_ij + 1.0) / 2.0
            pair_count += 1

    agreement_ratio = pair_sum / pair_count if pair_count > 0 else 1.0
    agreement_ratio = _clamp(agreement_ratio, 0.0, 1.0)

    # Named conflict classification
    # Indices: 0=Trend, 1=Gamma, 2=Structure, 3=Flow, 4=Vol
    if n >= 5:
        u1, u2, u3, u4, u5 = u_vals[0], u_vals[1], u_vals[2], u_vals[3], u_vals[4]

        # 1. CONF_GAMMA_TREND: Trend vs Gamma
        if (u1 > 0.50 and u2 < -0.40) or (u1 < -0.50 and u2 > 0.40):
            conflicts.append(
                PairwiseConflict(
                    conflict_code="CONF_GAMMA_TREND",
                    model_a=names[0],
                    model_b=names[1],
                    correlation=round(mat[0, 1], 4),
                    severity="HIGH",
                    explanation=(
                        f"Trend momentum ({u1:+.2f}) opposes dealer gamma posture ({u2:+.2f}). "
                        "Dealer hedging may accelerate volatility against trend direction."
                    ),
                )
            )

        # 2. CONF_FLOW_PRICE: Trend vs Flow
        if (u1 > 0.50 and u4 < -0.60) or (u1 < -0.50 and u4 > 0.60):
            conflicts.append(
                PairwiseConflict(
                    conflict_code="CONF_FLOW_PRICE",
                    model_a=names[0],
                    model_b=names[3],
                    correlation=round(mat[0, 3], 4),
                    severity="CRITICAL",
                    explanation=(
                        f"Price trend ({u1:+.2f}) diverges from institutional order flow ({u4:+.2f}). "
                        "Signals potential smart-money absorption/distribution into retail momentum."
                    ),
                )
            )

        # 3. CONF_VOL_EXPANSION: Trend vs Vol Shock
        if u1 > 0.60 and vol_state == "VOLATILITY_SHOCK":
            conflicts.append(
                PairwiseConflict(
                    conflict_code="CONF_VOL_EXPANSION",
                    model_a=names[0],
                    model_b=names[4],
                    correlation=round(mat[0, 4], 4),
                    severity="HIGH",
                    explanation=(
                        "Bullish price velocity co-occurring with realized volatility shock, "
                        "characteristic of short squeeze or expansion breakout."
                    ),
                )
            )

        # 4. CONF_STRUCT_MOMENTUM: Trend vs Mean-Reverting Structure
        vr_val = variance_ratio if variance_ratio is not None else 1.0
        hl_val = ou_half_life if ou_half_life is not None else 30.0
        if abs(u1) > 0.80 and vr_val < 0.85 and hl_val <= 10.0:
            conflicts.append(
                PairwiseConflict(
                    conflict_code="CONF_STRUCT_MOMENTUM",
                    model_a=names[0],
                    model_b=names[2],
                    correlation=round(mat[0, 2], 4),
                    severity="MEDIUM",
                    explanation=(
                        f"High velocity ({u1:+.2f}) inside mean-reverting structure "
                        f"(VR={vr_val:.2f}, half-life={hl_val:.1f}d). Vulnerable to range rejection."
                    ),
                )
            )

        # 5. CONF_GAMMA_FLOW: Gamma vs Flow
        if u2 > 0.60 and u4 < -0.70:
            conflicts.append(
                PairwiseConflict(
                    conflict_code="CONF_GAMMA_FLOW",
                    model_a=names[1],
                    model_b=names[3],
                    correlation=round(mat[1, 3], 4),
                    severity="HIGH",
                    explanation=(
                        "Dealer long-gamma pin suppresses spot while institutional flow exerts "
                        "directional selling stress. Barrier breach risk elevated."
                    ),
                )
            )

    return mat, round(agreement_ratio, 4), conflicts


# ---------------------------------------------------------------------------
# Calibrated Multi-Factor Confidence Scoring
# ---------------------------------------------------------------------------


def compute_q_data(
    n_bars: int,
    n_req: int = 252,
    n_min: int = 20,
    oi_total: Optional[float] = None,
    iv_fallbacks: int = 0,
    total_contracts: int = 0,
    has_flip: bool = True,
    has_options: bool = True,
    age_sec: float = 0.0,
    is_realtime: bool = False,
) -> float:
    """Compute data completeness factor Q_data in [0.0, 1.0]."""
    if n_bars < n_min:
        return 0.0

    q_bars = _clamp((n_bars - n_min) / float(max(1, n_req - n_min)), 0.0, 1.0)

    if has_options and oi_total is not None:
        q_oi = math.tanh(max(0.0, float(oi_total)) / 10000.0)
        q_iv = 1.0 - (
            float(iv_fallbacks) / float(max(1, total_contracts)) if total_contracts > 0 else 0.0
        )
        q_iv = _clamp(q_iv, 0.0, 1.0)
        q_flip = 1.0 if has_flip else 0.70
        q_chain = q_oi * q_iv * q_flip
    else:
        # Equities without options data receive baseline full weight for chain component
        q_chain = 1.0

    if is_realtime and age_sec > 0:
        q_fresh = math.exp(-max(0.0, age_sec - 60.0) / 900.0)
    else:
        q_fresh = 1.0

    q_data = q_bars * (0.35 + 0.65 * q_chain) * q_fresh
    return _clamp(q_data, 0.0, 1.0)


def compute_a_models(postures: Sequence[float]) -> float:
    """Compute normalized multi-model agreement consensus score in [0.0, 1.0]."""
    _, ratio, _ = build_agreement_matrix(postures)
    return ratio


def compute_d_boundary(
    spot: Optional[float],
    gamma_flip: Optional[float],
    kalman_z: float,
    delta_band: float = 0.010,
) -> float:
    """Compute distance from decision boundaries D_boundary in [0.0, 1.0]."""
    if spot is not None and spot > 0 and gamma_flip is not None and gamma_flip > 0:
        delta_flip = abs(spot - gamma_flip) / spot
        d_flip = math.tanh(delta_flip / delta_band)
    else:
        d_flip = 1.0

    d_trend = math.tanh(abs(abs(kalman_z) - 0.50) / 0.50)
    d_boundary = d_flip * (0.50 + 0.50 * d_trend)
    return _clamp(d_boundary, 0.0, 1.0)


def compute_s_persistence(
    n_unbroken_bars: int = 1,
    n_recent_flips: int = 1,
    tau_persist: float = 5.0,
) -> float:
    """Compute regime persistence and stability factor S_persistence in [0.0, 1.0]."""
    s_tenure = math.tanh(max(0, n_unbroken_bars) / tau_persist)
    w_penalty = math.exp(-0.35 * max(0, n_recent_flips - 1))
    s_persistence = s_tenure * w_penalty
    return _clamp(s_persistence, 0.0, 1.0)


def compute_t_risk_hazard(t_risk: float) -> float:
    """Compute transition hazard multiplier (1.0 - 0.5 * T_risk) in [0.50, 1.00]."""
    clamped_risk = _clamp(t_risk, 0.0, 1.0)
    return 1.0 - 0.50 * clamped_risk


def compute_calibrated_confidence(
    q_data: float,
    a_models: float,
    d_boundary: float,
    s_persistence: float,
    t_risk: float,
    *,
    z_extension: float = 0.0,
) -> float:
    """Multi-factor multiplicative calibrated confidence C in [0.0, 1.0]."""
    q = _clamp(q_data, 0.0, 1.0)
    a = _clamp(a_models, 0.0, 1.0)
    d = _clamp(d_boundary, 0.0, 1.0)
    s = _clamp(s_persistence, 0.0, 1.0)
    h = compute_t_risk_hazard(t_risk)

    # Extension penalty: penalize entering at extreme overextension (|z| > 2.0)
    abs_z = abs(float(z_extension))
    d_ext = _clamp(1.0 - max(0.0, (abs_z - 2.0) * 0.35), 0.30, 1.0)

    c = q * a * d * s * h * d_ext
    return _clamp(round(c, 4), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Strictly Normalized Probability Simplex Formulation
# ---------------------------------------------------------------------------


def compute_regime_probabilities(
    kalman_z: float,
    flow_mad_z: float,
    variance_ratio: float,
    net_gex_usd: Optional[float],
    delta_flip: Optional[float],
    vol_percentile: float,
    vol_state: str,
    t_risk: float,
    a_models: float,
    tau_0: float = 1.0,
) -> RegimeProbabilities:
    """Formulate 3-state probability distribution satisfying p_bull + p_bear + p_neutral = 1.0000 strictly."""
    # 1. Bullish evidence
    vr_trend_bull = max(0.0, (variance_ratio - 1.0) / 0.20) if kalman_z > 0 else 0.0
    gamma_bull = 0.4 if (net_gex_usd is not None and net_gex_usd > 0 and kalman_z > -0.5) else 0.0
    e_bull = (
        1.0 * max(0.0, kalman_z) + 0.8 * max(0.0, flow_mad_z) + 0.5 * vr_trend_bull + gamma_bull
    )

    # 2. Bearish evidence
    vr_trend_bear = max(0.0, (variance_ratio - 1.0) / 0.20) if kalman_z < 0 else 0.0
    gamma_bear = 0.4 if (net_gex_usd is not None and net_gex_usd < 0 and kalman_z < 0.5) else 0.0
    e_bear = (
        1.0 * max(0.0, -kalman_z) + 0.8 * max(0.0, -flow_mad_z) + 0.5 * vr_trend_bear + gamma_bear
    )

    # 3. Neutral evidence
    d_flip_val = abs(delta_flip) if delta_flip is not None else 1.0
    neutral_flip_bonus = 0.5 if (d_flip_val <= 0.0050 or vol_state == "COMPRESSION_LOW") else 0.0
    e_neutral = (
        0.9 * max(0.0, 1.5 - abs(kalman_z))
        + 1.6 * max(0.0, 0.50 - vol_percentile)
        + 0.7 * max(0.0, (1.0 - variance_ratio) / 0.20)
        + neutral_flip_bonus
    )

    # Dynamic temperature scaling
    tau = tau_0 * (1.0 + 1.5 * _clamp(t_risk, 0.0, 1.0) + 1.0 * (1.0 - _clamp(a_models, 0.0, 1.0)))
    tau = max(0.1, tau)

    # Stable Softmax
    e_vec = np.array([e_bull, e_bear, e_neutral], dtype=float)
    e_max = np.max(e_vec)
    z_vec = np.exp((e_vec - e_max) / tau)
    p_vec = z_vec / np.sum(z_vec)

    # Round to 4 decimal places with exact residual compensation
    p_bull = round(float(p_vec[0]), 4)
    p_bear = round(float(p_vec[1]), 4)
    p_neutral = round(float(p_vec[2]), 4)

    diff = 1.0 - (p_bull + p_bear + p_neutral)
    if abs(diff) > 1e-6:
        # Adjust the largest probability component
        if p_bull >= p_bear and p_bull >= p_neutral:
            p_bull = round(p_bull + diff, 4)
        elif p_bear >= p_bull and p_bear >= p_neutral:
            p_bear = round(p_bear + diff, 4)
        else:
            p_neutral = round(p_neutral + diff, 4)

    return RegimeProbabilities(
        bullish=p_bull,
        bearish=p_bear,
        neutral=p_neutral,
    )


# ---------------------------------------------------------------------------
# Master Layer 3 Deterministic Reconciliation Engine
# ---------------------------------------------------------------------------


def reconcile_market_regime(
    kalman_z: float,
    trend_state: str,
    vol_percentile: float,
    vol_state: VolatilityState,
    market_structure: MarketStructure,
    variance_ratio: float,
    ou_half_life: float,
    flow_mad_z: float,
    t_risk: float,
    delta_flip: Optional[float],
    agreement_ratio: float,
    has_model_conflict: bool,
    is_measurable: bool = True,
    *,
    upside_expansion: float = 0.0,
    downside_hazard: Optional[float] = None,
    z_extension: float = 0.0,
    dist_sma50: Optional[float] = None,
) -> PrimaryRegime:
    """Deterministic hierarchical aggregation ladder mapping specialized models to PrimaryRegime."""
    if not is_measurable:
        return PrimaryRegime.UNMEASURABLE

    # 1. Fail-Closed Triggers:
    # - Flip transition band proximity: |delta_flip| <= 0.25% (0.0025)
    # - Critical downside transition hazard: downside_hazard >= 0.65
    # - Low consensus or model conflict: A_models < 0.40 or has_model_conflict
    is_in_flip_band = delta_flip is not None and abs(delta_flip) <= 0.0025
    effective_hazard = downside_hazard if downside_hazard is not None else t_risk
    is_high_hazard = effective_hazard >= 0.65
    is_consensus_broken = agreement_ratio < 0.40 or has_model_conflict

    # Anti-Bottom Capitulation Guard:
    # If downside hazard is high and price is in deep capitulation washout (z_extension < -2.5),
    # force UNCERTAIN_TRANSITIONAL to prevent shorting into impending V-bottom squeezes.
    is_capitulation_washout = z_extension < -2.5 and effective_hazard >= 0.50

    if is_in_flip_band or is_high_hazard or is_consensus_broken or is_capitulation_washout:
        return PrimaryRegime.UNCERTAIN_TRANSITIONAL

    # 2. Volatility Expansion Breakout:
    # Elevated/shock volatility or strong upside expansion co-occurring with positive velocity/flow
    is_vol_elevated = (
        vol_state in (VolatilityState.ELEVATED_HIGH, VolatilityState.VOLATILITY_SHOCK)
        or upside_expansion >= 0.50
    )
    # Directional polarity: Breakout MUST have positive momentum (kalman_z >= 0.50 or flow_mad_z >= 0.50)
    # If velocity is negative (kalman_z <= -0.75), expanding volatility is a BEARISH breakdown, not an upside breakout.
    is_breakout_velocity = kalman_z >= 0.50 or (flow_mad_z >= 0.50 and kalman_z >= 0.0)
    is_structure_trending = market_structure in (
        MarketStructure.TRENDING,
        MarketStructure.RANGE_BOUND,
    )
    is_parabolic_expansion = z_extension > 3.0 and kalman_z >= 1.0

    if (is_vol_elevated and is_breakout_velocity and is_structure_trending) or is_parabolic_expansion:
        return PrimaryRegime.VOL_EXPANSION_BREAKOUT

    # 3. Directional Trends:
    # BULLISH_TREND: z_v >= 0.75, flow >= -0.50, struct in (TRENDING, RANGE_BOUND) or kalman_z >= 1.20
    if (
        kalman_z >= 0.75
        and flow_mad_z >= -0.50
        and (
            market_structure in (MarketStructure.TRENDING, MarketStructure.RANGE_BOUND)
            or kalman_z >= 1.20
        )
        and trend_state in ("BULLISH_TREND", "BULLISH_ACCELERATING")
    ):
        return PrimaryRegime.BULLISH_TREND

    # BEARISH_TREND: z_v <= -0.75, flow <= 0.50, struct in (TRENDING, RANGE_BOUND) or kalman_z <= -1.20
    # Also catches bearish volatility breakdowns: is_vol_elevated with negative velocity
    is_bear_breakdown = is_vol_elevated and kalman_z <= -0.75
    if (
        (
            kalman_z <= -0.75
            and flow_mad_z <= 0.50
            and (
                market_structure in (MarketStructure.TRENDING, MarketStructure.RANGE_BOUND)
                or kalman_z <= -1.20
            )
            and trend_state in ("BEARISH_TREND", "BEARISH_ACCELERATING")
        )
        or is_bear_breakdown
    ):
        if dist_sma50 is not None and dist_sma50 > 0.0 and not is_bear_breakdown:
            return PrimaryRegime.MEAN_REVERTING
        return PrimaryRegime.BEARISH_TREND

    # 4. Non-Directional Structures:
    # COMPRESSION_RANGE: Low volatility percentile, flat/low velocity, balanced flow
    if (
        vol_state == VolatilityState.COMPRESSION_LOW
        and abs(kalman_z) <= 0.75
        and abs(flow_mad_z) <= 1.25
    ):
        return PrimaryRegime.COMPRESSION_RANGE

    # MEAN_REVERTING: Structure model confirms mean reversion (VR < 0.85 & half-life <= 15d), velocity moderate
    if market_structure == MarketStructure.MEAN_REVERTING and abs(kalman_z) <= 1.20:
        return PrimaryRegime.MEAN_REVERTING

    # 5. Decisive Fallback: Resolve borderline states by predominant driver rather than cop-out uncertainty
    if kalman_z >= 0.75 and flow_mad_z >= -0.75:
        return PrimaryRegime.BULLISH_TREND
    if kalman_z <= -0.75 and flow_mad_z <= 0.75:
        if dist_sma50 is not None and dist_sma50 > 0.0:
            return PrimaryRegime.MEAN_REVERTING
        return PrimaryRegime.BEARISH_TREND
    if market_structure == MarketStructure.MEAN_REVERTING or variance_ratio < 0.90:
        return PrimaryRegime.MEAN_REVERTING
    if vol_state == VolatilityState.COMPRESSION_LOW or vol_percentile < 0.35:
        return PrimaryRegime.COMPRESSION_RANGE
    if vol_state in (VolatilityState.ELEVATED_HIGH, VolatilityState.VOLATILITY_SHOCK):
        return PrimaryRegime.VOL_EXPANSION_BREAKOUT

    return (
        PrimaryRegime.COMPRESSION_RANGE
        if abs(kalman_z) <= 0.50
        else (
            PrimaryRegime.BULLISH_TREND
            if kalman_z > 0
            else (
                PrimaryRegime.MEAN_REVERTING
                if dist_sma50 and dist_sma50 > 0
                else PrimaryRegime.BEARISH_TREND
            )
        )
    )



def compute_unified_market_regime(
    symbol: str,
    prices: pd.DataFrame,
    options_chain: Optional[pd.DataFrame] = None,
    asof: Optional[str] = None,
    config: Optional[RegimeFeatureConfig] = None,
    shared_levels: Optional[Any] = None,
) -> UnifiedMarketState:
    """Execute complete 3-layer reconciliation pipeline producing UnifiedMarketState."""
    from datetime import datetime, timezone
    from edge.research.regime_explainability import (
        generate_dynamic_explanation,
        generate_dynamic_explanation_unmeasurable,
    )

    cfg = config or RegimeFeatureConfig()
    asof_str = asof or datetime.now(timezone.utc).isoformat()

    # Measurability Validation
    if (
        prices is None
        or not isinstance(prices, pd.DataFrame)
        or prices.empty
        or len(prices) < 20
        or "close" not in prices.columns
    ):
        explanation = generate_dynamic_explanation_unmeasurable(
            "Insufficient price bar history (minimum 20 bars required)."
        )
        return UnifiedMarketState(
            symbol=symbol,
            spot=None,
            asof=asof_str,
            primary_regime=PrimaryRegime.UNMEASURABLE,
            confidence=0.0,
            volatility_state=VolatilityState.NORMAL_MEDIUM,
            market_structure=MarketStructure.RANGE_BOUND,
            flow_context=FlowContext.BALANCED_FLOW,
            transition_risk=1.0,
            probabilities=RegimeProbabilities(bullish=0.3333, bearish=0.3333, neutral=0.3334),
            model_agreement=ModelAgreement(
                overall_agreement=0.0,
                agreeing_models=[],
                conflicting_models=[],
                divergence_summary="Telemetry unmeasurable.",
                pairwise_matrix=None,
            ),
            explainability=explanation,
            levels=StructuralLevels(
                call_wall=None, put_wall=None, gamma_flip=None, session_vwap=None
            ),
            quality=QualityMetrics(
                measurable=False,
                data_completeness=0.0,
                reason="Insufficient price bar history (minimum 20 bars required).",
                missing_lenses=["Trend", "Volatility", "Structure", "Flow", "Gamma"],
            ),
            confidence_components=None,
        )

    # Extract clean close array and spot
    close_s = pd.to_numeric(prices["close"], errors="coerce").dropna()
    if (close_s <= 0).any() or len(close_s) < 20:
        explanation = generate_dynamic_explanation_unmeasurable(
            "Non-positive or invalid price data detected."
        )
        return UnifiedMarketState(
            symbol=symbol,
            spot=None,
            asof=asof_str,
            primary_regime=PrimaryRegime.UNMEASURABLE,
            confidence=0.0,
            volatility_state=VolatilityState.NORMAL_MEDIUM,
            market_structure=MarketStructure.RANGE_BOUND,
            flow_context=FlowContext.BALANCED_FLOW,
            transition_risk=1.0,
            probabilities=RegimeProbabilities(bullish=0.3333, bearish=0.3333, neutral=0.3334),
            model_agreement=ModelAgreement(
                overall_agreement=0.0,
                agreeing_models=[],
                conflicting_models=[],
                divergence_summary="Telemetry unmeasurable.",
                pairwise_matrix=None,
            ),
            explainability=explanation,
            levels=StructuralLevels(
                call_wall=None, put_wall=None, gamma_flip=None, session_vwap=None
            ),
            quality=QualityMetrics(
                measurable=False,
                data_completeness=0.0,
                reason="Non-positive or invalid price data detected.",
                missing_lenses=["Trend", "Volatility", "Structure", "Flow", "Gamma"],
            ),
            confidence_components=None,
        )

    spot = float(close_s.iloc[-1])
    n_bars = len(close_s)

    # -----------------------------------------------------------------------
    # Layer 1: Raw Point-in-Time Features
    # -----------------------------------------------------------------------
    layer1_feats = build_layer1_regime_features(prices, option_chain=options_chain, config=cfg)
    vwap_val = (
        float(layer1_feats["vwap"].iloc[-1])
        if "vwap" in layer1_feats.columns and pd.notna(layer1_feats["vwap"].iloc[-1])
        else None
    )
    flow_mad_z = (
        float(layer1_feats["flow_mad_z"].iloc[-1])
        if "flow_mad_z" in layer1_feats.columns and pd.notna(layer1_feats["flow_mad_z"].iloc[-1])
        else 0.0
    )

    # Options Chain & GEX Profile
    has_options = (
        options_chain is not None
        and isinstance(options_chain, pd.DataFrame)
        and not options_chain.empty
    )
    gex_data = (
        compute_dollar_gex_profile(options_chain, spot=spot, rate=cfg.risk_free_rate)
        if has_options
        else None
    )

    net_gex_usd = gex_data["net_gex_usd"] if gex_data else None
    gamma_flip = gex_data["gamma_flip"] if gex_data else None
    call_wall = gex_data["call_wall"] if gex_data else None
    put_wall = gex_data["put_wall"] if gex_data else None

    # Adopt shared levels measured upstream so the multi-model engine reconciles
    # identically with the microstructure and options surfaces.
    if shared_levels is not None:
        if getattr(shared_levels, "call_wall", None) is not None:
            call_wall = shared_levels.call_wall
        if getattr(shared_levels, "put_wall", None) is not None:
            put_wall = shared_levels.put_wall
        if getattr(shared_levels, "gamma_flip", None) is not None:
            gamma_flip = shared_levels.gamma_flip
        elif getattr(shared_levels, "gex_profile", None):
            try:
                from edge.research.microstructure_regime import _interpolate_profile, _nearest_flip

                gamma_flip = _nearest_flip(shared_levels.gex_profile, spot=spot)
                if net_gex_usd is None and spot is not None and spot > 0:
                    prof_gex = _interpolate_profile(shared_levels.gex_profile, spot=spot)
                    if prof_gex is not None and math.isfinite(prof_gex):
                        net_gex_usd = prof_gex * 1e6
            except Exception:
                pass

    delta_flip = (
        (spot - gamma_flip) / spot
        if (spot is not None and spot > 0 and gamma_flip is not None)
        else None
    )

    # -----------------------------------------------------------------------
    # Layer 2: Specialized Models
    # -----------------------------------------------------------------------
    # 1. Trend Model (Kalman with adaptive vol scaling & extension z-score)
    kt_res = kalman_trend(close_s, adaptive_vol_scaling=True)
    kalman_z = float(kt_res.score[-1])
    trend_state = str(kt_res.trend_state[-1])
    trend_persistence_bars = int(kt_res.persistence[-1])
    z_ext = (
        float(kt_res.extension_zscore[-1])
        if kt_res.extension_zscore is not None and pd.notna(kt_res.extension_zscore[-1])
        else 0.0
    )

    # Macro 50-day moving average distance for trend alignment / bull pullback detection
    dist_sma50: Optional[float] = None
    if len(close_s) >= 20:
        sma50_val = float(close_s.rolling(50, min_periods=20).mean().iloc[-1])
        if sma50_val > 0:
            dist_sma50 = (spot - sma50_val) / sma50_val

    # 2. Volatility Model (252d Rolling Percentile)
    vol_res = compute_rolling_volatility_regime(prices, vol_window=cfg.volatility_window)
    vol_pctile = (
        float(vol_res.volatility_percentile.iloc[-1])
        if pd.notna(vol_res.volatility_percentile.iloc[-1])
        else 0.50
    )
    raw_vol_state = str(vol_res.volatility_state.iloc[-1])
    vol_state_enum = (
        VolatilityState[raw_vol_state]
        if raw_vol_state in VolatilityState.__members__
        else VolatilityState.NORMAL_MEDIUM
    )

    # 3. Market Structure Model (Lo-MacKinlay VR & OU Half-Life)
    kalman_z_series = pd.Series(kt_res.score, index=close_s.index)
    struct_res = compute_market_structure(
        prices,
        vr_window=60,
        vr_lag=5,
        ou_window=30,
        kalman_z_series=kalman_z_series,
    )
    variance_ratio = (
        float(struct_res.variance_ratio_5.iloc[-1])
        if pd.notna(struct_res.variance_ratio_5.iloc[-1])
        else 1.0
    )
    ou_half_life = (
        float(struct_res.ou_half_life.iloc[-1])
        if pd.notna(struct_res.ou_half_life.iloc[-1])
        else 30.0
    )
    raw_struct_state = str(struct_res.market_structure.iloc[-1])
    struct_state_enum = (
        MarketStructure[raw_struct_state]
        if raw_struct_state in MarketStructure.__members__
        else MarketStructure.RANGE_BOUND
    )

    # 4. Transition Risk & Changepoint Model (CUSUM & BOCPD)
    bocpd_break_prob: Optional[pd.Series] = None
    if n_bars >= 15:
        try:
            rets_arr = np.log(close_s / close_s.shift(1)).dropna().to_numpy(dtype=float)
            bocpd_out = bocpd(
                rets_arr,
                GaussianVarianceModel(a=1.0, b=1e-4),
                ConstantHazard(lambda_gap=250.0),
            )
            # Align break_prob series
            bocpd_break_prob = pd.Series(
                np.concatenate([[0.0], bocpd_out.break_prob]), index=close_s.index
            )
        except Exception:
            bocpd_break_prob = None

    trans_res = compute_cusum_transition_risk(
        returns=layer1_feats["log_return"],
        bocpd_break_prob=bocpd_break_prob,
        vol_shock_mask=vol_res.volatility_shock,
    )
    t_risk = (
        float(trans_res.transition_risk.iloc[-1])
        if pd.notna(trans_res.transition_risk.iloc[-1])
        else 0.0
    )
    t_down = (
        float(trans_res.downside_hazard.iloc[-1])
        if trans_res.downside_hazard is not None and pd.notna(trans_res.downside_hazard.iloc[-1])
        else t_risk
    )
    t_up = (
        float(trans_res.upside_expansion.iloc[-1])
        if trans_res.upside_expansion is not None and pd.notna(trans_res.upside_expansion.iloc[-1])
        else 0.0
    )

    # 5. Flow Context Classification
    if flow_mad_z > 1.5:
        flow_context_enum = FlowContext.INSTITUTIONAL_ACCUMULATION
    elif flow_mad_z < -1.5:
        flow_context_enum = FlowContext.INSTITUTIONAL_DISTRIBUTION
    elif abs(flow_mad_z) <= 0.5 and vol_state_enum == VolatilityState.COMPRESSION_LOW:
        flow_context_enum = FlowContext.BALANCED_FLOW
    elif abs(kalman_z) > 1.0 and abs(flow_mad_z) <= 0.5:
        flow_context_enum = FlowContext.ABSORPTION_CHURN
    else:
        flow_context_enum = FlowContext.BALANCED_FLOW

    # -----------------------------------------------------------------------
    # Layer 3: Agreement Matrix, Confidence & Reconciliation
    # -----------------------------------------------------------------------
    gex_scale_usd = (
        max(abs(net_gex_usd), 1e6) if net_gex_usd is not None else (spot * 1e5 if spot else 1e6)
    )

    postures = compute_multi_model_postures(
        kalman_z=kalman_z,
        net_gex_usd=net_gex_usd,
        gex_scale_usd=gex_scale_usd,
        delta_flip=delta_flip,
        variance_ratio=variance_ratio,
        flow_mad_z=flow_mad_z,
        vol_percentile=vol_pctile,
    )

    agree_mat, agree_ratio, conflicts = build_agreement_matrix(
        postures=postures,
        vol_state=vol_state_enum.value,
        variance_ratio=variance_ratio,
        ou_half_life=ou_half_life,
    )

    model_names = [p.model_name for p in postures]
    agreeing_list = [
        p.model_name
        for p in postures
        if p.discrete_stance != 0 and (p.discrete_stance == postures[0].discrete_stance)
    ]
    conflicting_list = [
        p.model_name
        for p in postures
        if p.discrete_stance != 0 and (p.discrete_stance == -postures[0].discrete_stance)
    ]

    pairwise_dict: Dict[str, Dict[str, float]] = {}
    for i, name_i in enumerate(model_names):
        pairwise_dict[name_i] = {}
        for j, name_j in enumerate(model_names):
            pairwise_dict[name_i][name_j] = round(float(agree_mat[i, j]), 4)

    divergence_summary = (
        "; ".join(c.explanation for c in conflicts)
        if conflicts
        else (
            "All available models show directional alignment."
            if agree_ratio >= 0.70
            else "Moderate model dispersion."
        )
    )

    model_agreement = ModelAgreement(
        overall_agreement=agree_ratio,
        agreeing_models=agreeing_list,
        conflicting_models=conflicting_list,
        divergence_summary=divergence_summary,
        pairwise_matrix=pairwise_dict,
        conflicts=conflicts,
    )

    # Multi-Factor Calibrated Confidence
    total_contracts = len(options_chain) if has_options and options_chain is not None else 0
    iv_fallbacks = 0
    oi_total = 0.0
    if has_options and options_chain is not None:
        oi_col = options_chain.get("open_interest", options_chain.get("oi", 0.0))
        oi_total = float(pd.to_numeric(oi_col, errors="coerce").fillna(0.0).sum())

    q_data = compute_q_data(
        n_bars=n_bars,
        oi_total=oi_total if has_options else None,
        iv_fallbacks=iv_fallbacks,
        total_contracts=total_contracts,
        has_flip=(gamma_flip is not None),
        has_options=has_options,
    )
    d_boundary = compute_d_boundary(spot=spot, gamma_flip=gamma_flip, kalman_z=kalman_z)
    s_persistence = compute_s_persistence(n_unbroken_bars=trend_persistence_bars, n_recent_flips=1)
    t_hazard = compute_t_risk_hazard(t_risk)

    calibrated_conf = compute_calibrated_confidence(
        q_data=q_data,
        a_models=agree_ratio,
        d_boundary=d_boundary,
        s_persistence=s_persistence,
        t_risk=t_risk,
        z_extension=z_ext,
    )

    q_bars = _clamp((n_bars - 20) / (252 - 20), 0.0, 1.0)
    conf_components = ConfidenceComponents(
        q_data=q_data,
        q_bars=q_bars,
        q_chain=1.0 if not has_options else (q_data / max(1e-6, q_bars * 0.35)),
        q_freshness=1.0,
        a_models=agree_ratio,
        d_boundary=d_boundary,
        d_flip=math.tanh(abs(delta_flip) / 0.01) if delta_flip is not None else 1.0,
        d_trend=math.tanh(abs(abs(kalman_z) - 0.50) / 0.50),
        s_persistence=s_persistence,
        tenure_bars=trend_persistence_bars,
        whipsaw_penalty=1.0,
        t_risk=t_risk,
        hazard_multiplier=t_hazard,
        composite_confidence=calibrated_conf,
    )

    # Probabilities
    probs = compute_regime_probabilities(
        kalman_z=kalman_z,
        flow_mad_z=flow_mad_z,
        variance_ratio=variance_ratio,
        net_gex_usd=net_gex_usd,
        delta_flip=delta_flip,
        vol_percentile=vol_pctile,
        vol_state=vol_state_enum.value,
        t_risk=t_risk,
        a_models=agree_ratio,
    )

    # Reconcile Primary Regime
    has_critical_conflict = any(c.severity == "CRITICAL" for c in conflicts)
    primary_regime = reconcile_market_regime(
        kalman_z=kalman_z,
        trend_state=trend_state,
        vol_percentile=vol_pctile,
        vol_state=vol_state_enum,
        market_structure=struct_state_enum,
        variance_ratio=variance_ratio,
        ou_half_life=ou_half_life,
        flow_mad_z=flow_mad_z,
        t_risk=t_risk,
        delta_flip=delta_flip,
        agreement_ratio=agree_ratio,
        has_model_conflict=has_critical_conflict,
        is_measurable=True,
        upside_expansion=t_up,
        downside_hazard=t_down,
        z_extension=z_ext,
        dist_sma50=dist_sma50,
    )


    # -----------------------------------------------------------------------
    # Dynamic Explainability
    # -----------------------------------------------------------------------
    from edge.research.regime_explainability import FeatureZScores

    z_scores = FeatureZScores(
        trend=round(kalman_z, 4),
        gamma=round(postures[1].continuous_score * 3.0, 4) if has_options else 0.0,
        vol=round(float(np.clip((vol_pctile - 0.50) / 0.1667, -3.0, 3.0)), 4),
        flow=round(flow_mad_z, 4),
        structure=round(
            float(
                np.clip((variance_ratio - 1.0) / 0.15 * (1.0 if kalman_z >= 0 else -1.0), -3.0, 3.0)
            ),
            4,
        ),
    )

    levels_obj = StructuralLevels(
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        session_vwap=vwap_val,
    )

    explainability = generate_dynamic_explanation(
        primary_regime=primary_regime,
        confidence=calibrated_conf,
        z_scores=z_scores,
        levels=levels_obj,
        net_gex_usd=net_gex_usd,
        spot=spot,
        t_risk=t_risk,
        persistence_bars=trend_persistence_bars,
        vol_percentile=vol_pctile,
        variance_ratio=variance_ratio,
        ou_half_life=ou_half_life,
        conflicts=conflicts,
        has_options=has_options,
    )

    quality = QualityMetrics(
        measurable=True,
        data_completeness=q_data,
        reason=None,
        missing_lenses=[] if has_options else ["Gamma Topography"],
    )

    # Pillar metrics collection for downstream dashboard grids
    realized_vol_pct = (
        float(vol_res.realized_volatility.iloc[-1]) * 100.0
        if (
            hasattr(vol_res, "realized_volatility")
            and pd.notna(vol_res.realized_volatility.iloc[-1])
        )
        else None
    )
    parkinson_vol_pct = (
        float(layer1_feats["vol_parkinson"].iloc[-1]) * 100.0
        if (
            "vol_parkinson" in layer1_feats.columns
            and pd.notna(layer1_feats["vol_parkinson"].iloc[-1])
        )
        else None
    )

    # Estimate ATM IV from options chain if available
    atm_iv_pct: Optional[float] = None
    if (
        has_options
        and options_chain is not None
        and "strike" in options_chain.columns
        and "iv" in options_chain.columns
    ):
        try:
            near_strikes = options_chain[
                (options_chain["strike"] >= spot * 0.95) & (options_chain["strike"] <= spot * 1.05)
            ]
            valid_ivs = pd.to_numeric(near_strikes["iv"], errors="coerce").dropna()
            valid_ivs = valid_ivs[(valid_ivs >= 0.05) & (valid_ivs <= 3.0)]
            if not valid_ivs.empty:
                atm_iv_pct = float(valid_ivs.median()) * 100.0
        except Exception:
            atm_iv_pct = None

    iv_hv_ratio: Optional[float] = None
    if atm_iv_pct is not None and realized_vol_pct is not None and realized_vol_pct > 0:
        iv_hv_ratio = round(atm_iv_pct / realized_vol_pct, 2)

    # Hurst exponent estimated from variance ratio VR(q=5): VR ~ q^(2H-1) -> H ~ 0.5 * (1 + ln(VR)/ln(5))
    hurst_exp: Optional[float] = None
    if variance_ratio > 0:
        h_est = 0.5 * (1.0 + math.log(max(0.01, variance_ratio)) / math.log(5.0))
        hurst_exp = round(max(0.05, min(0.95, float(h_est))), 4)

    pillar_metrics = {
        "kalman_z": round(kalman_z, 4),
        "kalman_velocity": round(kalman_z * 0.001, 6),
        "trend_state": trend_state,
        "trend_persistence": trend_persistence_bars,
        "vol_percentile": round(vol_pctile, 4),
        "realized_vol_pct": round(realized_vol_pct, 2) if realized_vol_pct is not None else None,
        "parkinson_vol_pct": round(parkinson_vol_pct, 2) if parkinson_vol_pct is not None else None,
        "implied_vol_pct": round(atm_iv_pct, 2) if atm_iv_pct is not None else None,
        "iv_hv_ratio": iv_hv_ratio,
        "ou_half_life_bars": round(ou_half_life, 2) if ou_half_life is not None else None,
        "hurst_exponent": hurst_exp,
        "variance_ratio": round(variance_ratio, 4),
        "net_gex_m": round(net_gex_usd / 1e6, 2) if net_gex_usd is not None else None,
        "net_vex_m": (
            round(gex_data["net_vex_usd"] / 1e6, 2)
            if (gex_data and "net_vex_usd" in gex_data)
            else None
        ),
        "net_chex_m": (
            round(gex_data["net_chex_usd"] / 1e6, 2)
            if (gex_data and "net_chex_usd" in gex_data)
            else None
        ),
        "order_flow_delta_m": round(flow_mad_z * 10.0, 2) if flow_mad_z is not None else None,
    }

    return UnifiedMarketState(
        symbol=symbol,
        spot=spot,
        asof=asof_str,
        primary_regime=primary_regime,
        confidence=calibrated_conf,
        volatility_state=vol_state_enum,
        market_structure=struct_state_enum,
        flow_context=flow_context_enum,
        transition_risk=t_risk,
        probabilities=probs,
        model_agreement=model_agreement,
        explainability=explainability,
        levels=levels_obj,
        quality=quality,
        confidence_components=conf_components,
        pillar_metrics=pillar_metrics,
    )
