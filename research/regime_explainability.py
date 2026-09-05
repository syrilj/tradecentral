"""Dynamic Explainability Engine for Layer 3 Market Regimes.

Theoretical Foundations:
- Standardized Scale-Free Feature Attribution Vector:
    alpha = [alpha_trend, alpha_gamma, alpha_vol, alpha_flow, alpha_structure]^T
    where alpha_k = w_k * z_k in [-3.0, +3.0]
- Dynamic Weight Vector (w_k) with data availability masking (m_k) and contextual multipliers (beta_k),
  strictly guaranteeing sum(w_k) = 1.0 under any missing data permutation.
- Zero-Template Algorithmic Synthesis:
  Generates dynamic headlines, 4-sentence structured narrative summaries, ranked leading drivers,
  and explicit divergence/conflict reasoning without static canned text.
- Honest Zero-Spoofing: Withheld states output transparent explanations without fabricated placeholders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np


@dataclass(frozen=True)
class FeatureZScores:
    """Standardized point-in-time scale-free feature z-scores in [-3.0, 3.0]."""

    trend: float  # Kalman velocity z-score
    gamma: float  # Normalized dealer net GEX & flip proximity
    vol: float  # 252d Realized volatility percentile normal quantile
    flow: float  # Signed volume proxy MAD z-score
    structure: float  # Lo-MacKinlay Variance Ratio / Hurst persistence


# ---------------------------------------------------------------------------
# Dynamic Feature Attribution Vector Formulation
# ---------------------------------------------------------------------------


def compute_dynamic_weights(
    z_scores: FeatureZScores,
    measurable_mask: Sequence[int] = (1, 1, 1, 1, 1),
    t_risk: float = 0.0,
    delta_flip: Optional[float] = None,
) -> Dict[str, float]:
    """Compute dynamically normalized feature weights summing strictly to 1.0000."""
    # Base weights: Trend (0.25), Gamma (0.25), Vol (0.15), Flow (0.15), Structure (0.20)
    w0 = np.array([0.25, 0.25, 0.15, 0.15, 0.20], dtype=float)
    m = np.array([int(bool(x)) for x in measurable_mask], dtype=float)

    # Contextual multipliers beta_k
    beta = np.ones(5, dtype=float)
    if t_risk > 0.40:
        beta[2] = 1.5  # Vol
        beta[3] = 1.5  # Flow
        beta[0] = 0.6  # Trend (dampened during active hazard)

    if delta_flip is not None and abs(delta_flip) <= 0.0025:
        # Inside flip band: damp gamma weight
        beta[1] = max(0.1, abs(delta_flip) / 0.0025)

    raw_w = m * w0 * beta
    total_raw = np.sum(raw_w)

    if total_raw <= 1e-9:
        # If all masked out, return uniform on measurable or uniform overall
        if np.sum(m) > 0:
            norm_w = m / np.sum(m)
        else:
            norm_w = np.full(5, 0.20)
    else:
        norm_w = raw_w / total_raw

    keys = ["trend", "gamma", "vol", "flow", "structure"]
    out: Dict[str, float] = {}
    for i, k in enumerate(keys):
        out[k] = round(float(norm_w[i]), 4)

    # Residual adjustment to guarantee exact 1.0000 sum
    diff = 1.0 - sum(out.values())
    if abs(diff) > 1e-6:
        max_k = max(out, key=lambda k: out[k])
        out[max_k] = round(out[max_k] + diff, 4)

    return out


def compute_feature_attributions(
    z_scores: FeatureZScores,
    weights: Dict[str, float],
) -> Dict[str, float]:
    """Compute signed feature attribution vector alpha_k = w_k * z_k in [-3.0, 3.0]."""
    z_dict = {
        "trend": z_scores.trend,
        "gamma": z_scores.gamma,
        "vol": z_scores.vol,
        "flow": z_scores.flow,
        "structure": z_scores.structure,
    }
    alpha: Dict[str, float] = {}
    for k in ("trend", "gamma", "vol", "flow", "structure"):
        w_val = weights.get(k, 0.20)
        z_val = z_dict.get(k, 0.0)
        alpha[k] = round(float(np.clip(w_val * z_val, -3.0, 3.0)), 4)
    return alpha


# ---------------------------------------------------------------------------
# Algorithmic Synthesis & Headline Generator
# ---------------------------------------------------------------------------


def generate_dynamic_headline(
    primary_regime: Any,
    z_scores: FeatureZScores,
    attributions: Dict[str, float],
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None,
    gamma_flip: Optional[float] = None,
    net_gex_usd: Optional[float] = None,
    spot: Optional[float] = None,
    vol_percentile: float = 0.50,
    ou_half_life: float = 30.0,
    confidence: float = 0.50,
    reason: Optional[str] = None,
) -> str:
    """Generate dynamic headline without static template matching."""
    regime_str = (
        primary_regime.value if hasattr(primary_regime, "value") else str(primary_regime)
    ).upper()

    net_gex_m = net_gex_usd / 1e6 if net_gex_usd is not None else None
    zt = z_scores.trend
    zg = z_scores.gamma
    zv = z_scores.vol
    zf = z_scores.flow
    ag = attributions.get("gamma", 0.0)

    if regime_str == "UNMEASURABLE":
        msg = reason or "Open interest or price telemetry unavailable"
        return f"Regime Telemetry Withheld: {msg}"

    if regime_str == "UNCERTAIN_TRANSITIONAL":
        if gamma_flip is not None and spot is not None and abs(spot - gamma_flip) / spot <= 0.0025:
            return (
                f"Regime Uncertainty ({confidence*100:.0f}% Conf): Spot (${spot:.2f}) Pinned Near Zero-Gamma Flip (${gamma_flip:.2f})"
            )
        if abs(zt) > 1.0 and (zg < -0.5 or zf < -1.0 if zt > 0 else zg > 0.5 or zf > 1.0):
            return (
                f"Regime Uncertainty ({confidence*100:.0f}% Conf): Trend Model ({zt:+.1f}z) Diverges from Short Gamma Flow"
            )
        return f"Regime Uncertainty ({confidence*100:.0f}% Conf): Multi-Model Dispersion in Transition Zone"

    if regime_str == "VOL_EXPANSION_BREAKOUT":
        flow_desc = "Put Flow Acceleration" if zf < 0 else "Aggressive Bid Accumulation"
        return f"Volatility Expansion Breakout ({zv:+.1f}z Vol Shock) Driven by {flow_desc}"

    if regime_str == "COMPRESSION_RANGE":
        flip_str = f" Near Zero-Gamma Flip (${gamma_flip:.2f})" if gamma_flip is not None else ""
        return f"Volatility Compression ({vol_percentile*100:.0f}th %tile) with Pinning{flip_str}"

    if regime_str == "MEAN_REVERTING":
        return f"Mean-Reverting Oscillation ({ou_half_life:.1f} bar half-life) within Expected Move Envelope"

    if regime_str == "BULLISH_TREND":
        if ag < -0.20 or (net_gex_m is not None and net_gex_m < -5.0):
            wall_str = f"Overhead Call Wall (${call_wall:.2f}) and " if call_wall is not None else ""
            return f"Bullish Momentum ({zt:+.1f}z) Constrained by {wall_str}Short Gamma Acceleration Risk"
        if ag >= 0.20 or (net_gex_m is not None and net_gex_m > 5.0):
            return f"Sustained Bullish Trend ({zt:+.1f}z) with Dealer Gamma Dampening"
        return f"Clear Bullish Trend ({zt:+.1f}z) Supported by Market Structure"

    if regime_str == "BEARISH_TREND":
        if ag < -0.20 or (net_gex_m is not None and net_gex_m < -5.0):
            return f"Accelerating Bearish Breakdown ({zt:+.1f}z) in Short Gamma Cascade"
        if ag >= 0.20 or (net_gex_m is not None and net_gex_m > 5.0):
            wall_str = f" (${put_wall:.2f})" if put_wall is not None else ""
            return f"Bearish Momentum ({zt:+.1f}z) Approaching Put Wall Support{wall_str}"
        return f"Bearish Drift ({zt:+.1f}z) Driven by Institutional Selling Pressure"

    return f"Market in {regime_str.replace('_', ' ').title()} State ({confidence*100:.0f}% Confidence)"


# ---------------------------------------------------------------------------
# Dynamic 4-Sentence Narrative Summary Generator
# ---------------------------------------------------------------------------


def generate_dynamic_narrative(
    primary_regime: Any,
    confidence: float,
    attributions: Dict[str, float],
    z_scores: FeatureZScores,
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None,
    gamma_flip: Optional[float] = None,
    net_gex_usd: Optional[float] = None,
    spot: Optional[float] = None,
    t_risk: float = 0.0,
    persistence_bars: int = 1,
    vol_percentile: float = 0.50,
    variance_ratio: float = 1.0,
    ou_half_life: float = 30.0,
) -> str:
    """Generate dynamic 4-sentence structured narrative summary."""
    regime_str = (
        primary_regime.value if hasattr(primary_regime, "value") else str(primary_regime)
    ).upper()

    if regime_str == "UNMEASURABLE":
        return "Market regime telemetry is withheld due to insufficient historical bars or unobserved market quotes. All quantitative inferences are suspended to prevent false precision."

    # Conviction band
    if confidence >= 0.75:
        conf_band = f"High Conviction ({confidence*100:.0f}%)"
    elif confidence >= 0.45:
        conf_band = f"Moderate Confidence ({confidence*100:.0f}%)"
    else:
        conf_band = f"Low Confidence ({confidence*100:.0f}%)"

    f_net = sum(attributions.values())
    clean_regime_name = regime_str.replace("_", " ").title()

    # Sentence 1: Core Regime & Conviction
    s1 = f"Market is in a **{clean_regime_name}** regime (net force F_net = {f_net:+.2f}) with **{conf_band}**."

    # Sentence 2: Lead Evidence
    sorted_pos = sorted(
        [(k, v) for k, v in attributions.items() if v > 0],
        key=lambda x: x[1],
        reverse=True,
    )
    sorted_neg = sorted(
        [(k, v) for k, v in attributions.items() if v < 0],
        key=lambda x: x[1],
    )

    if regime_str in ("BULLISH_TREND", "VOL_EXPANSION_BREAKOUT") or (regime_str not in ("BEARISH_TREND",) and f_net >= 0):
        lead_drivers = []
        if sorted_pos:
            top_k, top_v = sorted_pos[0]
            if top_k == "trend":
                lead_drivers.append(f"strong Kalman velocity ({z_scores.trend:+.2f}z)")
            elif top_k == "structure":
                lead_drivers.append(f"persistent market structure (VR: {variance_ratio:.2f})")
            elif top_k == "flow":
                lead_drivers.append(f"institutional bid flow (+{z_scores.flow:.2f}z)")
            elif top_k == "vol":
                lead_drivers.append(f"expanding volatility environment ({vol_percentile*100:.1f}th %tile)")
            elif top_k == "gamma":
                lead_drivers.append("stabilizing dealer long-gamma positioning")

            if len(sorted_pos) > 1:
                sec_k, sec_v = sorted_pos[1]
                if sec_k == "trend":
                    lead_drivers.append(f"Kalman velocity ({z_scores.trend:+.2f}z)")
                elif sec_k == "structure":
                    lead_drivers.append(f"market structure (VR: {variance_ratio:.2f})")
                elif sec_k == "flow":
                    lead_drivers.append(f"positive order flow (+{z_scores.flow:.2f}z)")
                elif sec_k == "vol":
                    lead_drivers.append("elevated volatility expansion")
                elif sec_k == "gamma":
                    lead_drivers.append("supportive gamma profile")

        if lead_drivers:
            s2 = f"Upward drift is driven by {' and '.join(lead_drivers)}."
        else:
            s2 = f"Price drift reflects steady upward momentum across trailing {persistence_bars} bars."
    else:
        lead_drivers = []
        if sorted_neg:
            top_k, top_v = sorted_neg[0]
            if top_k == "trend":
                lead_drivers.append(f"negative Kalman velocity ({z_scores.trend:+.2f}z)")
            elif top_k == "structure":
                lead_drivers.append(f"directional trending breakdown (VR: {variance_ratio:.2f})")
            elif top_k == "flow":
                lead_drivers.append(f"institutional distribution flow ({z_scores.flow:+.2f}z)")
            elif top_k == "vol":
                lead_drivers.append("elevated volatility shock")
            elif top_k == "gamma":
                lead_drivers.append("dealer short-gamma acceleration")

        if lead_drivers:
            s2 = f"Downward pressure is driven by {' and '.join(lead_drivers)}."
        else:
            s2 = f"Price action reflects sustained selling pressure across trailing {persistence_bars} bars."

    # Sentence 3: Headwinds & Structural Pins
    net_gex_m = net_gex_usd / 1e6 if net_gex_usd is not None else None
    headwind_parts = []
    if net_gex_m is not None:
        if net_gex_m < -5.0:
            headwind_parts.append(f"dealers are short gamma (-${abs(net_gex_m):.1f}M/1%), amplifying volatility")
        elif net_gex_m > 5.0:
            headwind_parts.append(f"dealers are long gamma (+${net_gex_m:.1f}M/1%), providing volatility dampening")

    if call_wall is not None and spot is not None and spot < call_wall:
        dist_cw = (call_wall - spot) / spot * 100
        headwind_parts.append(f"overhead Call Wall barrier at ${call_wall:.2f} (+{dist_cw:.1f}%)")
    if put_wall is not None and spot is not None and spot > put_wall:
        dist_pw = (spot - put_wall) / spot * 100
        headwind_parts.append(f"Put Wall support at ${put_wall:.2f} (-{dist_pw:.1f}%)")

    if headwind_parts:
        s3 = f"However, {', with '.join(headwind_parts)}."
    else:
        s3 = f"Volatility environment sits at the {vol_percentile*100:.1f}th percentile with OU half-life of {ou_half_life:.1f} bars."

    # Sentence 4: Stability & Changepoint Risk
    if t_risk > 0.40:
        hazard_desc = f"elevated ({t_risk*100:.0f}%)"
    else:
        hazard_desc = f"low ({t_risk*100:.0f}%)"
    s4 = f"Transition hazard is {hazard_desc} with {persistence_bars} consecutive bars of unbroken regime persistence."

    return f"{s1} {s2} {s3} {s4}"


# ---------------------------------------------------------------------------
# Ranked Leading Drivers & Conflict Reasoning
# ---------------------------------------------------------------------------


def rank_leading_drivers(
    attributions: Dict[str, float],
    z_scores: FeatureZScores,
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None,
    gamma_flip: Optional[float] = None,
    net_gex_usd: Optional[float] = None,
    vol_percentile: float = 0.50,
    variance_ratio: float = 1.0,
    ou_half_life: float = 30.0,
    persistence_bars: int = 1,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Rank feature drivers by absolute attribution magnitude."""
    drivers_list: List[Dict[str, Any]] = []
    drivers_formatted: List[str] = []

    net_gex_m = net_gex_usd / 1e6 if net_gex_usd is not None else None

    # Descriptions for each feature
    desc_map = {
        "trend": f"Kalman velocity {z_scores.trend:+.2f}z with {persistence_bars} bars persistence",
        "structure": f"Lo-MacKinlay VR(5) at {variance_ratio:.2f} (OU half-life: {ou_half_life:.1f}d)",
        "gamma": (
            f"Net GEX ${net_gex_m:+.1f}M/1%"
            + (f", Flip: ${gamma_flip:.2f}" if gamma_flip is not None else "")
            if net_gex_m is not None
            else "Options gamma profile unmeasured"
        ),
        "flow": f"Signed volume flow proxy MAD z-score at {z_scores.flow:+.2f}z",
        "vol": f"20d realized volatility at {vol_percentile*100:.1f}th percentile",
    }

    z_val_map = {
        "trend": z_scores.trend,
        "gamma": z_scores.gamma,
        "vol": z_scores.vol,
        "flow": z_scores.flow,
        "structure": z_scores.structure,
    }

    # Sort descending by |alpha|
    sorted_features = sorted(
        attributions.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    )

    for feat, alpha_val in sorted_features:
        z_val = z_val_map.get(feat, 0.0)
        desc = desc_map.get(feat, "")
        sign_str = "+" if alpha_val >= 0 else "-"
        drivers_list.append(
            {
                "feature": feat.capitalize(),
                "value": round(z_val, 4),
                "contribution": round(alpha_val, 4),
                "description": desc,
            }
        )
        drivers_formatted.append(f"{sign_str} {feat.capitalize()}: {desc}")

    return drivers_list, drivers_formatted


def surface_divergences_and_conflicts(
    z_scores: FeatureZScores,
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None,
    gamma_flip: Optional[float] = None,
    net_gex_usd: Optional[float] = None,
    spot: Optional[float] = None,
    t_risk: float = 0.0,
    variance_ratio: float = 1.0,
    ou_half_life: float = 30.0,
    vol_percentile: float = 0.50,
    conflicts: Optional[Sequence[Any]] = None,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Surface specific risk factors, uncertainty sources, and transition alerts."""
    risk_factors: List[str] = []
    uncertainty_sources: List[str] = []
    transition_alert: Optional[str] = None

    net_gex_m = net_gex_usd / 1e6 if net_gex_usd is not None else None
    zt = z_scores.trend
    zg = z_scores.gamma
    zf = z_scores.flow
    zv = z_scores.vol

    # 1. Trend vs Gamma Clash
    if (zt > 1.0 and net_gex_m is not None and net_gex_m < -5.0) or (zt < -1.0 and net_gex_m is not None and net_gex_m > 5.0):
        wall_str = f" near ${call_wall:.2f}" if call_wall is not None else ""
        uncertainty_sources.append(
            f"Model Conflict: Bullish trend ({zt:+.1f}z) conflicts with dealer Short Gamma posture (-${abs(net_gex_m):.1f}M/1%). Dealer hedging amplifies downside slippage if spot rejects overhead barriers{wall_str}."
        )
        risk_factors.append("Short gamma acceleration risk if spot turns against trend momentum.")

    # 2. Trend vs Structure Clash
    if abs(zt) > 1.0 and variance_ratio < 0.85 and ou_half_life <= 12.0:
        uncertainty_sources.append(
            f"Structural Divergence: Price momentum ({zt:+.1f}z) contradicts mean-reverting market structure (VR: {variance_ratio:.2f}, half-life: {ou_half_life:.1f} bars). Trend is vulnerable to momentum exhaustion."
        )
        risk_factors.append("Mean-reverting structure threatens trend continuation.")

    # 3. Volatility Shock vs Price Action
    if zv > 1.5 and vol_percentile > 0.85:
        risk_factors.append(f"Realized volatility shock ({vol_percentile*100:.1f}th percentile) elevates gap and tail risk.")
        if abs(zt) < 0.5:
            uncertainty_sources.append(
                f"Volatility Anomaly: Realized volatility shock (+{zv:.1f}z, {vol_percentile*100:.0f}th %tile) coiling within a compressed price range. Imminent breakout hazard."
            )

    # 4. Order Flow vs Price Disconnect
    if (zt > 0.5 and zf < -1.5) or (zt < -0.5 and zf > 1.5):
        uncertainty_sources.append(
            f"Flow Divergence: Spot moving counter to institutional order flow ({zf:+.1f}z delta). Indicates smart money absorption into retail momentum."
        )
        risk_factors.append("Institutional order flow divergence.")

    # 5. Boundary Proximity Warning
    if spot is not None and gamma_flip is not None and spot > 0:
        d_flip_pct = abs(spot - gamma_flip) / spot * 100
        if d_flip_pct <= 0.25:
            uncertainty_sources.append(
                f"Boundary Proximity: Spot (${spot:.2f}) is within {d_flip_pct:.2f}% of Zero-Gamma Flip (${gamma_flip:.2f}), entering neutral transition band."
            )
            risk_factors.append(f"Zero-Gamma Flip proximity (${gamma_flip:.2f}) creates unstable regime boundary.")

    # 6. Changepoint / Transition Hazard Alert
    if t_risk >= 0.40:
        transition_alert = f"Changepoint Hazard: Transition hazard is elevated ({t_risk*100:.0f}%), signaling active regime instability."
        uncertainty_sources.append(f"Elevated Changepoint Hazard (T_risk: {t_risk:.2f}).")
        risk_factors.append("High probability of imminent regime shift.")

    # Walls as resistance / support risks
    if call_wall is not None and spot is not None and spot < call_wall:
        dist_cw = (call_wall - spot) / spot * 100
        if dist_cw <= 1.5:
            risk_factors.append(f"Overhead Call Wall barrier resistance at ${call_wall:.2f} (+{dist_cw:.1f}%).")

    if put_wall is not None and spot is not None and spot > put_wall:
        dist_pw = (spot - put_wall) / spot * 100
        if dist_pw <= 1.5:
            risk_factors.append(f"Put Wall cushion support at ${put_wall:.2f} (-{dist_pw:.1f}%).")

    return risk_factors, uncertainty_sources, transition_alert


# ---------------------------------------------------------------------------
# Master Dynamic Explainability Entrypoint
# ---------------------------------------------------------------------------


def generate_dynamic_explanation(
    primary_regime: Any,
    confidence: float,
    z_scores: FeatureZScores,
    levels: Any,
    net_gex_usd: Optional[float] = None,
    spot: Optional[float] = None,
    t_risk: float = 0.0,
    persistence_bars: int = 1,
    vol_percentile: float = 0.50,
    variance_ratio: float = 1.0,
    ou_half_life: float = 30.0,
    conflicts: Optional[Sequence[Any]] = None,
    has_options: bool = True,
) -> Any:
    """Generate complete DynamicExplainability payload matching interface contracts."""
    from edge.research.regime_engine import DynamicExplainability

    call_wall = getattr(levels, "call_wall", None) if levels else None
    put_wall = getattr(levels, "put_wall", None) if levels else None
    gamma_flip = getattr(levels, "gamma_flip", None) if levels else None

    delta_flip = (
        (spot - gamma_flip) / spot
        if (spot is not None and spot > 0 and gamma_flip is not None)
        else None
    )

    mask = (1, 1 if has_options else 0, 1, 1, 1)
    weights = compute_dynamic_weights(
        z_scores=z_scores,
        measurable_mask=mask,
        t_risk=t_risk,
        delta_flip=delta_flip,
    )
    attributions = compute_feature_attributions(z_scores=z_scores, weights=weights)

    headline = generate_dynamic_headline(
        primary_regime=primary_regime,
        z_scores=z_scores,
        attributions=attributions,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        net_gex_usd=net_gex_usd,
        spot=spot,
        vol_percentile=vol_percentile,
        ou_half_life=ou_half_life,
        confidence=confidence,
    )

    summary_text = generate_dynamic_narrative(
        primary_regime=primary_regime,
        confidence=confidence,
        attributions=attributions,
        z_scores=z_scores,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        net_gex_usd=net_gex_usd,
        spot=spot,
        t_risk=t_risk,
        persistence_bars=persistence_bars,
        vol_percentile=vol_percentile,
        variance_ratio=variance_ratio,
        ou_half_life=ou_half_life,
    )

    drivers_list, _ = rank_leading_drivers(
        attributions=attributions,
        z_scores=z_scores,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        net_gex_usd=net_gex_usd,
        vol_percentile=vol_percentile,
        variance_ratio=variance_ratio,
        ou_half_life=ou_half_life,
        persistence_bars=persistence_bars,
    )

    risk_factors, uncertainty_sources, transition_alert = surface_divergences_and_conflicts(
        z_scores=z_scores,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        net_gex_usd=net_gex_usd,
        spot=spot,
        t_risk=t_risk,
        variance_ratio=variance_ratio,
        ou_half_life=ou_half_life,
        vol_percentile=vol_percentile,
        conflicts=conflicts,
    )

    return DynamicExplainability(
        summary_text=summary_text,
        leading_drivers=drivers_list,
        transition_alert=transition_alert,
        headline=headline,
        risk_factors=risk_factors,
        uncertainty_sources=uncertainty_sources,
    )


def generate_dynamic_explanation_unmeasurable(reason: str) -> Any:
    """Generate honest unmeasurable explainability object with zero spoofed metrics."""
    from edge.research.regime_engine import DynamicExplainability

    return DynamicExplainability(
        summary_text=f"Regime telemetry withheld: {reason}",
        leading_drivers=[],
        transition_alert="Telemetry unavailable; all regime signals withheld.",
        headline=f"Regime Telemetry Withheld: {reason}",
        risk_factors=["Insufficient data for regime identification."],
        uncertainty_sources=[reason],
    )
