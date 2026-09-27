"""Desk Multi-Dimensional Regime Fusion Adapter.

Bridges the Layer 3 Reconciliation Engine (`research/regime_engine.py`) with
API endpoints and dashboard contracts (`dashboard/src/regimeContracts.ts`).
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from edge.research.regime_engine import (
    FlowContext,
    MarketStructure,
    PrimaryRegime,
    UnifiedMarketState,
    VolatilityState,
    compute_unified_market_regime,
)


def _safe_float(val: Any, decimals: int = 4) -> Optional[float]:
    """Safely cast to float with decimal rounding, returning None for NaNs or non-finites."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, decimals)
    except (TypeError, ValueError):
        return None


def format_market_regime_payload(
    state: UnifiedMarketState,
    *,
    cache_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Format UnifiedMarketState into camelCase JSON matching MarketRegimePayload contract."""
    # Primary mapping
    primary_wire_map = {
        PrimaryRegime.BULLISH_TREND: "bull_trend",
        PrimaryRegime.BEARISH_TREND: "bear_trend",
        PrimaryRegime.COMPRESSION_RANGE: "compression_range",
        PrimaryRegime.MEAN_REVERTING: "mean_reverting",
        PrimaryRegime.VOL_EXPANSION_BREAKOUT: "vol_expansion_breakout",
        PrimaryRegime.UNCERTAIN_TRANSITIONAL: "uncertain_transitional",
        PrimaryRegime.UNMEASURABLE: "unmeasurable",
    }
    primary_wire = primary_wire_map.get(state.primary_regime, "uncertain_transitional")
    primary_label = state.primary_regime.value.replace("_", " ").title()

    # Confidence Band
    conf_score = _safe_float(state.confidence, 4) or 0.0
    if conf_score >= 0.75:
        conf_band = "high"
    elif conf_score >= 0.45:
        conf_band = "moderate"
    else:
        conf_band = "low"

    # Confidence penalty factors
    penalty_factors: List[str] = []
    if state.confidence_components:
        cc = state.confidence_components
        if cc.a_models < 0.60:
            penalty_factors.append(f"Model disagreement penalty (consensus: {cc.a_models*100:.0f}%)")
        if cc.d_boundary < 0.60:
            penalty_factors.append(f"Boundary proximity penalty (D_boundary: {cc.d_boundary:.2f})")
        if cc.t_risk > 0.40:
            penalty_factors.append(f"Active transition hazard penalty (T_risk: {cc.t_risk*100:.0f}%)")
        if cc.q_data < 0.70:
            penalty_factors.append(f"Data completeness penalty (Q_data: {cc.q_data*100:.0f}%)")

    # Trend Context
    trend_state_wire = "unmeasured"
    kalman_z = None
    kalman_v = None
    trend_persist = None
    if state.quality.measurable:
        pm = state.pillar_metrics or {}
        kalman_z = _safe_float(pm.get("kalman_z"))
        if kalman_z is None and state.explainability.leading_drivers:
            for d in state.explainability.leading_drivers:
                if d.get("feature") == "Trend":
                    kalman_z = _safe_float(d.get("value"))
                    break
        if kalman_z is None:
            kalman_z = 0.0

        if kalman_z >= 1.5:
            trend_state_wire = "strong_up"
        elif kalman_z >= 0.4:
            trend_state_wire = "up"
        elif kalman_z <= -1.5:
            trend_state_wire = "strong_down"
        elif kalman_z <= -0.4:
            trend_state_wire = "down"
        else:
            trend_state_wire = "flat"

        kalman_v = _safe_float(pm.get("kalman_velocity")) or _safe_float(kalman_z * 0.001, 6)
        trend_persist = _safe_float(pm.get("trend_persistence"))
        if trend_persist is None and state.confidence_components:
            trend_persist = _safe_float(state.confidence_components.s_persistence, 4)

    # Volatility Context
    vol_state_wire = {
        VolatilityState.COMPRESSION_LOW: "compression",
        VolatilityState.NORMAL_MEDIUM: "normal",
        VolatilityState.ELEVATED_HIGH: "elevated",
        VolatilityState.VOLATILITY_SHOCK: "shock",
    }.get(state.volatility_state, "normal")

    # Structure Context
    struct_state_wire = {
        MarketStructure.TRENDING: "trending",
        MarketStructure.MEAN_REVERTING: "mean_reverting",
        MarketStructure.RANGE_BOUND: "range_bound",
    }.get(state.market_structure, "range_bound")

    # Flow Context
    flow_state_wire = {
        FlowContext.INSTITUTIONAL_ACCUMULATION: "accumulation",
        FlowContext.INSTITUTIONAL_DISTRIBUTION: "distribution",
        FlowContext.ABSORPTION_CHURN: "churn",
        FlowContext.BALANCED_FLOW: "balanced",
    }.get(state.flow_context, "balanced")

    dealer_gamma_regime = "unmeasurable"
    net_gex_m = None
    if state.quality.measurable:
        if state.levels.gamma_flip is not None and state.spot is not None:
            dist_flip = (state.spot - state.levels.gamma_flip) / state.spot
            if abs(dist_flip) <= 0.0025:
                dealer_gamma_regime = "flip"
            elif dist_flip > 0:
                dealer_gamma_regime = "long"
            else:
                dealer_gamma_regime = "short"
        elif "Gamma Topography" not in state.quality.missing_lenses:
            dealer_gamma_regime = "long"

    # Transition Risk
    t_risk_val = _safe_float(state.transition_risk, 4) or 0.0
    if t_risk_val >= 0.70:
        trans_level = "critical"
    elif t_risk_val >= 0.45:
        trans_level = "high"
    elif t_risk_val >= 0.25:
        trans_level = "moderate"
    else:
        trans_level = "low"

    # Agreement Band
    agree_score = _safe_float(state.model_agreement.overall_agreement, 4) or 0.0
    if state.model_agreement.conflicts and any(c.severity == "CRITICAL" for c in state.model_agreement.conflicts):
        agree_band = "conflict"
    elif agree_score >= 0.75:
        agree_band = "high"
    elif agree_score >= 0.45:
        agree_band = "moderate"
    else:
        agree_band = "low"

    # Leading drivers formatted as strings
    driver_strings = [
        f"{d['feature']}: {d['description']}" for d in state.explainability.leading_drivers
    ]

    # Pillar metrics extraction
    pm = getattr(state, "pillar_metrics", None) or {}
    realized_vol_pct = _safe_float(pm.get("realized_vol_pct"), 2)
    vol_percentile = _safe_float(pm.get("vol_percentile"), 4)
    parkinson_vol_pct = _safe_float(pm.get("parkinson_vol_pct"), 2)
    implied_vol_pct = _safe_float(pm.get("implied_vol_pct"), 2)
    iv_hv_ratio = _safe_float(pm.get("iv_hv_ratio"), 2)

    ou_half_life = _safe_float(pm.get("ou_half_life_bars"), 1)
    hurst_exp = _safe_float(pm.get("hurst_exponent"), 2)

    gex_m = _safe_float(pm.get("net_gex_m"), 2)
    if gex_m is not None:
        net_gex_m = gex_m
    net_vex_m = _safe_float(pm.get("net_vex_m"), 2)
    net_chex_m = _safe_float(pm.get("net_chex_m"), 2)
    order_flow_delta_m = _safe_float(pm.get("order_flow_delta_m"), 2)

    hedging_pressure_dir = "neutral"
    if net_gex_m is not None:
        if net_gex_m > 0:
            hedging_pressure_dir = "supportive"
        elif net_gex_m < 0:
            hedging_pressure_dir = "pressuring"

    payload: Dict[str, Any] = {
        "symbol": state.symbol,
        "asof_utc": state.asof,
        "spot": _safe_float(state.spot, 4),
        "primary": primary_wire,
        "primaryLabel": primary_label,
        "confidence": {
            "score": conf_score,
            "band": conf_band,
            "penaltyFactors": penalty_factors,
        },
        "trend": {
            "state": trend_state_wire,
            "slope": kalman_v,
            "kalmanVelocity": kalman_v,
            "kalmanZScore": kalman_z,
            "trendPersistence": trend_persist,
            "measured": state.quality.measurable,
        },
        "volatility": {
            "state": vol_state_wire if state.quality.measurable else "unmeasured",
            "realizedVolPct": realized_vol_pct,
            "impliedVolPct": implied_vol_pct,
            "volPercentile": vol_percentile,
            "parkinsonVolPct": parkinson_vol_pct,
            "ivHvRatio": iv_hv_ratio,
            "measured": state.quality.measurable and (vol_percentile is not None or realized_vol_pct is not None),
        },
        "structure": {
            "state": struct_state_wire if state.quality.measurable else "unmeasured",
            "ouHalfLifeBars": ou_half_life,
            "hurstExponent": hurst_exp,
            "breakoutZScore": None,
            "exhaustionZScore": None,
            "measured": state.quality.measurable and (ou_half_life is not None or hurst_exp is not None),
        },
        "flow": {
            "state": flow_state_wire if state.quality.measurable else "unmeasured",
            "dealerGammaRegime": dealer_gamma_regime,
            "netGexM": net_gex_m,
            "netVexM": net_vex_m,
            "netCharmDriftM": net_chex_m,
            "orderFlowDeltaM": order_flow_delta_m,
            "hedgingPressureDirection": hedging_pressure_dir,
            "measured": state.quality.measurable and ("Gamma Topography" not in state.quality.missing_lenses) and (net_gex_m is not None),
        },
        "transition": {
            "level": trans_level,
            "changepointProb5d": t_risk_val,
            "changepointProb20d": min(1.0, t_risk_val * 1.2),
            "mapRunLength": state.confidence_components.tenure_bars if state.confidence_components else 1,
            "expectedRunLength": (state.confidence_components.tenure_bars * 1.2) if state.confidence_components else 1.0,
            "stabilityScore": round(1.0 - t_risk_val, 4),
            "measured": state.quality.measurable,
        },
        "agreement": {
            "band": agree_band,
            "agreementScore": agree_score,
            "agreeingModels": state.model_agreement.agreeing_models,
            "conflictingModels": state.model_agreement.conflicting_models,
            "divergenceSummary": state.model_agreement.divergence_summary,
            "pairwiseMatrix": state.model_agreement.pairwise_matrix,
        },
        "explanation": {
            "headline": state.explainability.headline or state.explainability.summary_text,
            "summary": state.explainability.summary_text,
            "leadingDrivers": driver_strings,
            "riskFactors": state.explainability.risk_factors,
            "uncertaintySources": state.explainability.uncertainty_sources,
        },
        "levels": {
            "callWall": _safe_float(state.levels.call_wall, 2),
            "putWall": _safe_float(state.levels.put_wall, 2),
            "gammaFlip": _safe_float(state.levels.gamma_flip, 2),
            "sessionVwap": _safe_float(state.levels.session_vwap, 2),
        },
        "quality": {
            "measurable": state.quality.measurable,
            "missingLenses": state.quality.missing_lenses,
            "reason": state.quality.reason,
        },
        "cache": cache_meta or {"hit": False, "age_seconds": 0.0, "ttl_seconds": 60.0},
    }

    return payload


def build_market_regime_payload(
    symbol: str,
    prices: pd.DataFrame,
    options_chain: Optional[pd.DataFrame] = None,
    asof_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute reconciliation and format directly into MarketRegimePayload dictionary."""
    state = compute_unified_market_regime(
        symbol=symbol,
        prices=prices,
        options_chain=options_chain,
        asof=asof_utc,
    )
    return format_market_regime_payload(state)
