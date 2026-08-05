"""Pure GEX / gamma-squeeze math shared by options intelligence.

Two layers:

1. **Charting GEX** (call-positive / put-negative) — wall levels, flip, desk UI.
   This is the industry display convention; it is *not* true dealer inventory.

2. **Theory squeeze** (direction-neutral short gamma + directional flow/momentum):
   A gamma squeeze is direction-neutral by itself. Short dealer gamma amplifies
   whichever way price is already moving; direction comes from the initial shock
   (call vs put flow imbalance × return momentum).

   Core identities (dealer short-premium inventory assumption q = −OI):

       DollarGamma_j = OI_j · M · Γ_j · S² · 0.01
       GEX_1%        = Σ_j q_j/|q_j| · DollarGamma_j   with q_j = −OI_j
                     = −Σ_j DollarGamma_j   (always ≤ 0 under short-premium)

       dH = −G · dS     (dealer hedge shares)
       Q  ≈ −DG · r     (dealer hedge notional for return r)

       r  = r₀ / (1 + λ · DG)     linear impact model
       F  = λ · |DG|              feedback when DG < 0
       amp = 1 / (1 − F)          amplification factor (F < 1)

   Squeeze risk (fuel, unsigned):

       SR = |GEX⁻_1%| / ADV · exp(−c · T) · (ATM_γ / total_γ)

   Directional scores:

       bullish = SR · max(0, call_imbalance) · max(0, momentum)
       bearish = SR · max(0, put_imbalance)  · max(0, −momentum)
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Black–Scholes gamma (when provider gamma is missing)
# ---------------------------------------------------------------------------

def bs_gamma(
    *,
    spot: float,
    strike: float,
    years: float,
    iv: float,
    rate: float = 0.045,
) -> float | None:
    """Black–Scholes gamma Γ = φ(d₁) / (S σ √T). Returns None if inputs invalid."""
    if spot <= 0 or strike <= 0 or years <= 0 or not 0.005 <= iv <= 5.0:
        return None
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * years) / (iv * root_t)
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi) / (spot * iv * root_t)


# ---------------------------------------------------------------------------
# Primitive hedge math (unit-testable against worked examples)
# ---------------------------------------------------------------------------

def dollar_gamma_1pct(
    open_interest: float,
    gamma: float,
    spot: float,
    *,
    multiplier: float = 100.0,
) -> float:
    """Dollar gamma for a 1% underlying move: OI · M · Γ · S² · 0.01."""
    if open_interest <= 0 or gamma <= 0 or spot <= 0 or multiplier <= 0:
        return 0.0
    return float(open_interest) * float(multiplier) * float(gamma) * (float(spot) ** 2) * 0.01


def dealer_option_delta_shares(
    q: float,
    delta: float,
    *,
    multiplier: float = 100.0,
) -> float:
    """Dealer option delta in shares: q · M · Δ (q < 0 when dealer short)."""
    return float(q) * float(multiplier) * float(delta)


def hedge_shares_for_delta(dealer_option_delta: float) -> float:
    """Delta-neutral hedge inventory H = −D_options."""
    return -float(dealer_option_delta)


def hedge_share_change(
    q: float,
    gamma: float,
    dS: float,
    *,
    multiplier: float = 100.0,
) -> float:
    """
    Change in required hedge shares for a spot move dS.

    dH ≈ −q · M · Γ · dS
    (aggregate: dH = −G · dS with G = Σ q M Γ)
    """
    g = float(q) * float(multiplier) * float(gamma)
    return -g * float(dS)


def dealer_hedge_flow_notional(dollar_gamma: float, r: float) -> float:
    """
    Approximate dealer trade notional caused by return r.

    Q ≈ −DollarGamma · r
    Positive Q = dealer buys underlying.
    """
    return -float(dollar_gamma) * float(r)


def amplification_factor(feedback_f: float) -> float | None:
    """
    Move amplification under short gamma: 1 / (1 − F), F = λ|DG|.

    Returns None when F ≥ 1 (linear model unstable).
    """
    f = float(feedback_f)
    if f >= 1.0:
        return None
    if f < 0.0:
        # Long-gamma dampening expressed as F_long = λ DG > 0 in the dual form;
        # callers should use impact_return for the general case.
        return 1.0 / (1.0 - f) if f != 1.0 else None
    return 1.0 / (1.0 - f)


def impact_return(r0: float, lambda_impact: float, dollar_gamma: float) -> float:
    """
    Closed-form return under linear impact + gamma feedback:

        r = r₀ / (1 + λ · DG)

    DG > 0 dampens; DG < 0 amplifies while 1 + λ DG > 0.
    """
    denom = 1.0 + float(lambda_impact) * float(dollar_gamma)
    if abs(denom) < 1e-15:
        return math.copysign(float("inf"), r0)
    return float(r0) / denom


def delta_after_move(delta0: float, gamma: float, dS: float) -> float:
    """Δ_new ≈ Δ_old + Γ · ΔS."""
    return float(delta0) + float(gamma) * float(dS)


# ---------------------------------------------------------------------------
# Theory squeeze risk + directional scores
# ---------------------------------------------------------------------------

def short_premium_gex_1pct_m(
    rows: Sequence[Mapping[str, Any]],
    *,
    spot: float,
) -> dict[str, float]:
    """
    Dealer GEX under customer-long / dealer-short premium (q = −OI).

    Returns components in $M for a 1% move (same scale as charting net_gex_m).
    All short-premium contributions are ≤ 0.
    """
    if spot <= 0:
        return {
            "total_gex_m": 0.0,
            "call_gex_m": 0.0,
            "put_gex_m": 0.0,
            "abs_gex_m": 0.0,
            "atm_abs_gex_m": 0.0,
            "atm_share": 0.0,
            "weighted_dte": 0.0,
        }

    call_m = 0.0
    put_m = 0.0
    atm_abs = 0.0
    dte_w_sum = 0.0
    dte_w = 0.0
    atm_band = 0.02 * spot

    for row in rows:
        oi = float(row.get("open_interest") or row.get("oi") or 0.0)
        gamma = float(row.get("gamma") or 0.0)
        mult = float(row.get("multiplier") or 100.0)
        strike = float(row.get("strike") or 0.0)
        right = str(row.get("right") or row.get("option_type") or "").lower()
        if right in {"c", "call"}:
            right = "call"
        elif right in {"p", "put"}:
            right = "put"
        if oi <= 0 or gamma <= 0 or right not in {"call", "put"}:
            continue
        # Dealer short the OI → negative dollar gamma
        dg_m = -dollar_gamma_1pct(oi, gamma, spot, multiplier=mult) / 1_000_000.0
        if right == "call":
            call_m += dg_m
        else:
            put_m += dg_m
        if abs(strike - spot) <= atm_band:
            atm_abs += abs(dg_m)
        dte = row.get("dte")
        if dte is not None:
            try:
                dte_f = max(0.0, float(dte))
            except (TypeError, ValueError):
                dte_f = 0.0
            w = abs(dg_m)
            dte_w_sum += dte_f * w
            dte_w += w

    total = call_m + put_m
    abs_total = abs(call_m) + abs(put_m)
    return {
        "total_gex_m": total,
        "call_gex_m": call_m,
        "put_gex_m": put_m,
        "abs_gex_m": abs_total,
        "atm_abs_gex_m": atm_abs,
        "atm_share": (atm_abs / abs_total) if abs_total > 1e-12 else 0.0,
        "weighted_dte": (dte_w_sum / dte_w) if dte_w > 1e-12 else 30.0,
    }


def squeeze_risk(
    *,
    neg_gex_1pct_m: float,
    adv_m: float,
    atm_share: float,
    weighted_dte: float,
    urgency_c: float = 0.05,
) -> float:
    """
    Unsigned squeeze risk:

        SR = |GEX⁻_1%| / ADV · e^{−c T} · ATM_share

    ``neg_gex_1pct_m`` is *signed* dealer GEX in $M for a 1% move.
    Only negative GEX contributes fuel: |GEX⁻| = max(0, −GEX).
    ADV is average daily dollar volume in $M.
    """
    fuel = max(0.0, -float(neg_gex_1pct_m))
    adv = max(float(adv_m), 1e-6)
    t = max(0.0, float(weighted_dte))
    urgency = math.exp(-float(urgency_c) * t)
    atm = max(0.0, min(1.0, float(atm_share)))
    return (fuel / adv) * urgency * atm


def directional_squeeze_scores(
    *,
    squeeze_risk_value: float,
    call_imbalance: float,
    put_imbalance: float | None = None,
    momentum: float,
    fuel_scale: float = 40.0,
    mom_ref: float = 0.01,
    flow_weight: float = 0.5,
) -> dict[str, float]:
    """
    Directional scores (theory, fuel-scaled conviction blend):

        fuel_ui   = tanh(fuel_scale · SR)          ∈ [0, 1)
        flow_call = max(0, call_imb)               ∈ [0, 1]
        flow_put  = max(0, put_imb)                ∈ [0, 1]
        mom_up    = clip(max(0, mom) / mom_ref, 1)
        mom_dn    = clip(max(0, −mom) / mom_ref, 1)

        conv_bull = w · flow_call + (1 − w) · mom_up
        conv_bear = w · flow_put  + (1 − w) · mom_dn

        bullish = fuel_ui · conv_bull              ∈ [0, 1)
        bearish = fuel_ui · conv_bear              ∈ [0, 1)

    Fuel stays *multiplicative*: no short dealer gamma ⇒ no squeeze, either way.
    Direction is *additive* across flow and momentum. The previous form
    multiplied the two directional gates, so any disagreement between them sent
    both legs to exactly zero — and since ``mom_up`` and ``mom_dn`` can never be
    positive together, ``bullish`` and ``bearish`` could never both be nonzero,
    leaving the ``two_way`` readout unreachable. A call-dominated tape into a
    falling price is one of the most common configurations on liquid names; it
    is a loaded two-way condition, not an absence of one.
    """
    sr = max(0.0, float(squeeze_risk_value))
    c_imb = float(call_imbalance)
    if put_imbalance is None:
        p_imb = -c_imb
    else:
        p_imb = float(put_imbalance)
    mom = float(momentum)
    ref = max(float(mom_ref), 1e-6)
    w_flow = max(0.0, min(1.0, float(flow_weight)))
    w_mom = 1.0 - w_flow
    fuel_ui = math.tanh(float(fuel_scale) * sr)
    flow_call = max(0.0, min(1.0, c_imb))
    flow_put = max(0.0, min(1.0, p_imb))
    mom_up = max(0.0, min(1.0, max(0.0, mom) / ref))
    mom_dn = max(0.0, min(1.0, max(0.0, -mom) / ref))
    conv_bull = w_flow * flow_call + w_mom * mom_up
    conv_bear = w_flow * flow_put + w_mom * mom_dn
    bull = fuel_ui * conv_bull
    bear = fuel_ui * conv_bear
    return {
        "squeeze_risk": sr,
        "fuel_ui": fuel_ui,
        "bullish_score": bull,
        "bearish_score": bear,
        "call_imbalance": c_imb,
        "put_imbalance": p_imb,
        "momentum": mom,
        "mom_up_gate": mom_up,
        "mom_dn_gate": mom_dn,
        "conviction_bull": conv_bull,
        "conviction_bear": conv_bear,
        "flow_weight": w_flow,
        "net_directional": bull - bear,
    }


def compute_theory_squeeze(
    *,
    chain_rows: Sequence[Mapping[str, Any]],
    spot: float,
    adv_notional: float,
    call_imbalance: float,
    momentum: float,
    put_imbalance: float | None = None,
    urgency_c: float = 0.05,
    score_scale: float = 40.0,
    fuel_scale: float = 40.0,
    mom_ref: float = 0.01,
    flow_weight: float = 0.5,
) -> dict[str, Any]:
    """
    Full theory squeeze readout.

    ``adv_notional`` is average daily dollar volume (not $M).
    ``call_imbalance`` is (call − put) / (call + put) on premium, volume, or OI.
    ``momentum`` is a simple return (e.g. close/close_n − 1).
    """
    gex = short_premium_gex_1pct_m(chain_rows, spot=spot)
    adv_m = max(float(adv_notional), 0.0) / 1_000_000.0
    neg_gex = gex["total_gex_m"]  # ≤ 0 under short-premium
    sr = squeeze_risk(
        neg_gex_1pct_m=neg_gex,
        adv_m=adv_m if adv_m > 0 else 1.0,
        atm_share=gex["atm_share"],
        weighted_dte=gex["weighted_dte"],
        urgency_c=urgency_c,
    )
    direction = directional_squeeze_scores(
        squeeze_risk_value=sr,
        call_imbalance=call_imbalance,
        put_imbalance=put_imbalance,
        momentum=momentum,
        fuel_scale=fuel_scale,
        mom_ref=mom_ref,
        flow_weight=flow_weight,
    )

    # Scores already in [0, 1); map to UI points. score_scale retained for API compat
    # but gates are the primary calibration (fuel_scale / mom_ref).
    bull_raw = direction["bullish_score"]
    bear_raw = direction["bearish_score"]
    bull_ui = 100.0 * bull_raw
    bear_ui = 100.0 * bear_raw
    signed = max(-100.0, min(100.0, bull_ui - bear_ui))

    if signed >= 20 and bull_ui >= 20:
        label = "bullish_squeeze"
    elif signed <= -20 and bear_ui >= 20:
        label = "bearish_squeeze"
    else:
        label = "neutral"

    return {
        "method": "theory_short_premium_gex_flow_momentum",
        "squeeze_score": round(signed, 1),
        "squeeze_label": label,
        "bullish_ui": round(bull_ui, 2),
        "bearish_ui": round(bear_ui, 2),
        "squeeze_risk": sr,
        "bullish_score_raw": bull_raw,
        "bearish_score_raw": bear_raw,
        "short_premium_gex_m": gex,
        "adv_m": adv_m,
        "call_imbalance": direction["call_imbalance"],
        "put_imbalance": direction["put_imbalance"],
        "momentum": direction["momentum"],
        "components": {
            "neg_gex_1pct_m": gex["total_gex_m"],
            "call_short_gex_m": gex["call_gex_m"],
            "put_short_gex_m": gex["put_gex_m"],
            "atm_share": gex["atm_share"],
            "weighted_dte": gex["weighted_dte"],
            "urgency": math.exp(-urgency_c * gex["weighted_dte"]),
            "liquidity_ratio": (abs(gex["total_gex_m"]) / adv_m) if adv_m > 0 else None,
            "squeeze_risk": sr,
            "fuel_ui": direction["fuel_ui"],
            "call_imbalance": direction["call_imbalance"],
            "put_imbalance": direction["put_imbalance"],
            "momentum": direction["momentum"],
            "mom_up_gate": direction["mom_up_gate"],
            "mom_dn_gate": direction["mom_dn_gate"],
            "conviction_bull": direction["conviction_bull"],
            "conviction_bear": direction["conviction_bear"],
            "score_scale": score_scale,
            "fuel_scale": fuel_scale,
            "mom_ref": mom_ref,
            "flow_weight": direction["flow_weight"],
        },
    }


# ---------------------------------------------------------------------------
# Legacy structure score (wall proximity UI — kept for factor boards)
# ---------------------------------------------------------------------------

def compute_squeeze_score(
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
    flip: float | None,
    near_net: float,
    net_dealer: float,
    otm_call_weight: float,
    otm_put_weight: float,
    total_weight: float,
    by_strike: list[dict[str, Any]],
    expected_move_pct: float | None,
    expected_move_low: float | None,
    expected_move_high: float | None,
) -> dict[str, Any]:
    """Legacy desk structure score (walls / OTM conc). Not a theory trade signal.

    Prefer ``compute_theory_squeeze`` for bullish/bearish gamma-squeeze math.
    Kept so factor boards remain readable under long-gamma dampening.
    """
    total_weight = max(float(total_weight), 1.0)
    call_wall_gex = 0.0
    put_wall_gex = 0.0
    for row in by_strike:
        strike = float(row.get("strike") or 0)
        if call_wall is not None and abs(strike - call_wall) < 1e-9:
            call_wall_gex = abs(float(row.get("call_gex") or 0.0))
        if put_wall is not None and abs(strike - put_wall) < 1e-9:
            put_wall_gex = abs(float(row.get("put_gex") or 0.0))

    em_pct = expected_move_pct if (expected_move_pct is not None and expected_move_pct > 0.1) else 5.0

    call_wall_dist_pct = ((call_wall - spot) / spot * 100) if call_wall is not None and spot > 0 else 999.0
    if -em_pct <= call_wall_dist_pct <= em_pct:
        call_prox_score = 30.0 * (1 - abs(call_wall_dist_pct) / em_pct)
    else:
        call_prox_score = 0.0

    put_wall_dist_pct = ((put_wall - spot) / spot * 100) if put_wall is not None and spot > 0 else 999.0
    if -em_pct <= put_wall_dist_pct <= em_pct:
        put_prox_score = -30.0 * (1 - abs(put_wall_dist_pct) / em_pct)
    else:
        put_prox_score = 0.0

    call_conc = otm_call_weight / total_weight
    put_conc = otm_put_weight / total_weight
    call_conc_score = min(15.0, call_conc * 100)
    put_conc_score = -min(15.0, put_conc * 100)

    if call_wall_gex > 0 and put_wall_gex > 0:
        wall_ratio = call_wall_gex / put_wall_gex
    elif call_wall_gex > 0:
        wall_ratio = float("inf")
    elif put_wall_gex > 0:
        wall_ratio = 0.0
    else:
        wall_ratio = 1.0
    if wall_ratio > 2:
        wall_asym_score = 10.0
    elif wall_ratio < 0.5:
        wall_asym_score = -10.0
    else:
        wall_asym_score = 0.0

    em_score = 0.0
    if expected_move_low is not None and expected_move_high is not None and spot > 0:
        if call_wall is not None and call_prox_score > 0:
            if call_wall <= expected_move_high:
                em_score = 10.0
            else:
                overshoot_pct = (call_wall - expected_move_high) / spot * 100
                em_score = max(0.0, 10.0 - overshoot_pct * 4)
        elif put_wall is not None and put_prox_score < 0:
            if put_wall >= expected_move_low:
                em_score = -10.0
            else:
                overshoot_pct = (expected_move_low - put_wall) / spot * 100
                em_score = min(0.0, -10.0 + overshoot_pct * 4)

    flip_score = 0.0
    if flip is not None and spot > 0:
        dist_flip_pct = abs((flip - spot) / spot * 100)
        if dist_flip_pct <= 3:
            if spot > flip and call_prox_score > 0:
                flip_score = 5.0
            elif spot < flip and put_prox_score < 0:
                flip_score = -5.0

    structural = (
        call_prox_score + put_prox_score + call_conc_score + put_conc_score
        + wall_asym_score + em_score + flip_score
    )
    direction = 0.0
    if structural > 0:
        direction = 1.0
    elif structural < 0:
        direction = -1.0

    structure_components = {
        "call_prox_score": call_prox_score,
        "put_prox_score": put_prox_score,
        "call_conc_score": call_conc_score,
        "put_conc_score": put_conc_score,
        "wall_asym_score": wall_asym_score,
        "em_score": em_score,
        "flip_score": flip_score,
    }

    if near_net < 0 and direction != 0:
        negative_fuel = min(1.0, abs(near_net) / max(1.0, abs(net_dealer)))
        regime_score = 20.0 * direction * negative_fuel
        scale = negative_fuel
        dampened = False
    else:
        negative_fuel = 0.0
        regime_score = 0.0
        scale = 0.12
        dampened = True

    scored_call_prox = call_prox_score * scale
    scored_put_prox = put_prox_score * scale
    scored_call_conc = call_conc_score * scale
    scored_put_conc = put_conc_score * scale
    scored_wall_asym = wall_asym_score * scale
    scored_em = em_score * scale
    scored_flip = flip_score * scale

    score = (
        regime_score + scored_call_prox + scored_put_prox + scored_call_conc
        + scored_put_conc + scored_wall_asym + scored_em + scored_flip
    )
    score = max(-100.0, min(100.0, score))

    if score >= 20:
        label = "bullish_squeeze"
    elif score <= -20:
        label = "bearish_squeeze"
    else:
        label = "neutral"

    return {
        "squeeze_score": round(score, 1),
        "squeeze_label": label,
        "squeeze_components": {
            "regime_score": round(regime_score, 3),
            "call_prox_score": round(scored_call_prox, 3),
            "put_prox_score": round(scored_put_prox, 3),
            "call_conc_score": round(scored_call_conc, 3),
            "put_conc_score": round(scored_put_conc, 3),
            "wall_asym_score": round(scored_wall_asym, 3),
            "em_score": round(scored_em, 3),
            "flip_score": round(scored_flip, 3),
        },
        "structure_components": {
            "regime_score": round(regime_score, 3),
            **{k: round(v, 3) for k, v in structure_components.items()},
        },
        "call_wall_gex": call_wall_gex,
        "put_wall_gex": put_wall_gex,
        "negative_fuel": round(negative_fuel, 4),
        "long_gamma_dampened": dampened,
        "structure_scale": round(scale, 4),
    }


def directional_walls(
    gex_rows: list[dict[str, Any]],
    *,
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
) -> tuple[float | None, float | None]:
    """Resistance above spot / support below spot (not global argmax which can flip sides)."""
    cw, pw = call_wall, put_wall
    if not gex_rows or spot <= 0:
        return cw, pw
    up = [r for r in gex_rows if float(r.get("strike") or 0) > spot]
    dn = [r for r in gex_rows if float(r.get("strike") or 0) < spot]
    if up:
        best = max(up, key=lambda r: float(r.get("call_gex_m") or r.get("call_gex") or 0))
        if float(best.get("call_gex_m") or best.get("call_gex") or 0) > 0:
            cw = float(best["strike"])
    if dn:
        best = min(dn, key=lambda r: float(r.get("put_gex_m") or r.get("put_gex") or 0))
        if float(best.get("put_gex_m") or best.get("put_gex") or 0) < 0:
            pw = float(best["strike"])
    return cw, pw


def near_spot_net_gex(
    gex_rows: list[dict[str, Any]],
    *,
    spot: float,
    band_pct: float = 0.05,
) -> float:
    """Sum net GEX for strikes within ±band_pct of spot (same units as rows)."""
    if not gex_rows or spot <= 0:
        return 0.0
    lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
    total = 0.0
    for r in gex_rows:
        k = float(r.get("strike") or 0)
        if lo <= k <= hi:
            total += float(r.get("net_gex_m") or r.get("net_gex") or 0)
    return total
