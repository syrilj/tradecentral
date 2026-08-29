"""Microstructure Regime Dynamics: Dealer Greeks, Surface Topography & Hedging Flows.

Implements institutional second- and third-order Black-Scholes Greeks, aggregate
dealer inventory positioning (GEX, VEX, CHEX, Speed, Zomma), the zero-gamma flip
level, structural boundary walls (Call Wall, Put Wall, Volatility Trigger), 4-quadrant
topography classification, and total instantaneous notional hedging flow.

Theoretical Foundations:
  1. Second-Order Hedging Differential:
     dDelta_dealer = Gamma * dS + Vanna * dSigma + Charm * dt
     F_hedge = GEX_net * (dS/dt) + VEX_net * (dSigma/dt) + CHEX_net

  2. GEX Formulation:
     GEX_K = Gamma_K * OI_K * 100 * S^2 * 0.01
     GEX_net(S) = sum_K [ phi_call * Gamma_{C,K}(S) * OI_{C,K} - phi_put * Gamma_{P,K}(S) * OI_{P,K} ] * 100 * S^2 * 0.01

  3. VEX & CHEX Cross-Sensitivities:
     VEX = dDelta / dSigma = - (d2 / sigma) * phi(d1) * sqrt(tau)
     CHEX = dDelta / dt = phi(d1) * [ (r * d2) / (sigma * sqrt(tau)) - (d2) / (2 * tau) ]

  4. Topographical Quadrants:
     - Forward Positive Ramp: S > S*, high GEX stacked overhead (mean-reverting grind, strike pins)
     - Backward Positive Ramp: S > S*, heavy GEX cushion below spot (strong downside support)
     - Forward Negative Slide: S < S*, deep negative GEX below (liquidity cascade / acceleration)
     - Backward Negative Slide: S < S*, deep negative GEX overhead (violent short-squeeze)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Mathematical Constants & Standard Normal Helpers
# ---------------------------------------------------------------------------
_SQRT_2PI = math.sqrt(2.0 * math.pi)
_SQRT_2 = math.sqrt(2.0)
_DEFAULT_RATE = 0.045
_MIN_IV = 0.005
_MAX_IV = 5.0
_MIN_TIME_YEARS = 1.0 / (365.25 * 24.0 * 60.0)  # ~1 minute


def _phi(x: float) -> float:
    """Standard normal probability density function: phi(x) = (1 / sqrt(2*pi)) * exp(-0.5 * x^2)."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _Phi(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / _SQRT_2))


# ---------------------------------------------------------------------------
# Black-Scholes Greeks (1st, 2nd, and 3rd order)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OptionGreeks:
    """Complete Greek profile for a single contract."""
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    vanna: float
    charm: float
    speed: float
    zomma: float
    d1: float
    d2: float


def bs_d1_d2(
    *,
    spot: float,
    strike: float,
    years: float,
    iv: float,
    rate: float = _DEFAULT_RATE,
) -> tuple[float, float] | None:
    """Compute Black-Scholes d1 and d2 parameters. Returns None if invalid."""
    if spot <= 0 or strike <= 0 or years <= 0 or not _MIN_IV <= iv <= _MAX_IV:
        return None
    tau = max(years, _MIN_TIME_YEARS)
    root_t = math.sqrt(tau)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * tau) / (iv * root_t)
    d2 = d1 - iv * root_t
    return d1, d2


def calculate_option_greeks(
    *,
    spot: float,
    strike: float,
    years: float,
    iv: float,
    right: str,
    rate: float = _DEFAULT_RATE,
) -> OptionGreeks | None:
    """Calculate 1st, 2nd, and 3rd order Black-Scholes Greeks for a contract.

    Args:
        spot: Current underlying price ($).
        strike: Option strike price ($).
        years: Time to expiration in years (tau).
        iv: Implied volatility as a decimal (e.g. 0.20 for 20%).
        right: 'call' ('c') or 'put' ('p').
        rate: Risk-free interest rate (e.g. 0.045 for 4.5%).

    Returns:
        OptionGreeks object or None if inputs invalid.
    """
    d1_d2 = bs_d1_d2(spot=spot, strike=strike, years=years, iv=iv, rate=rate)
    if d1_d2 is None:
        return None
    d1, d2 = d1_d2
    tau = max(years, _MIN_TIME_YEARS)
    root_t = math.sqrt(tau)
    phi_d1 = _phi(d1)
    is_call = right.strip().lower() in {"c", "call", "calls"}

    # 1. Delta
    if is_call:
        delta = _Phi(d1)
    else:
        delta = _Phi(d1) - 1.0  # -Phi(-d1)

    # 2. Gamma (identical for Call and Put)
    gamma = phi_d1 / (spot * iv * root_t)

    # 3. Vega (per 1.00 vol point move, i.e. 100% IV move)
    vega = spot * root_t * phi_d1

    # 4. Theta (per calendar day: dPrice / dt where dt = 1/365.25)
    df = math.exp(-rate * tau)
    if is_call:
        theta_annual = -(spot * phi_d1 * iv) / (2.0 * root_t) - rate * strike * df * _Phi(d2)
    else:
        theta_annual = -(spot * phi_d1 * iv) / (2.0 * root_t) + rate * strike * df * _Phi(-d2)
    theta = theta_annual / 365.25

    # 5. Rho (per 1% interest rate change)
    if is_call:
        rho = strike * tau * df * _Phi(d2) * 0.01
    else:
        rho = -strike * tau * df * _Phi(-d2) * 0.01

    # 6. Vanna = dDelta / dSigma = dVega / dS
    # Formula: -phi(d1) * d2 / iv (delta change per 1.00 IV move)
    vanna = -phi_d1 * d2 / iv

    # 7. Charm = dDelta / dt (Delta decay per calendar day, t = calendar time)
    # Using dTau = -dt:
    # dDelta / dt = - dDelta / dTau = phi(d1) * [ (rate * d2) / (iv * root_t) - d2 / (2 * tau) ]
    # Normalized to 1 calendar day (divide annual rate by 365.25):
    charm_annual = phi_d1 * ((rate * d2) / (iv * root_t) - d2 / (2.0 * tau))
    charm = charm_annual / 365.25

    # 8. Speed = dGamma / dS = - (Gamma / S) * (d1 / (iv * root_t) + 1)
    speed = -(gamma / spot) * (d1 / (iv * root_t) + 1.0)

    # 9. Zomma = dGamma / dSigma = Gamma * ( (d1 * d2 - 1) / iv )
    zomma = gamma * ((d1 * d2 - 1.0) / iv)

    return OptionGreeks(
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho,
        vanna=vanna,
        charm=charm,
        speed=speed,
        zomma=zomma,
        d1=d1,
        d2=d2,
    )


# ---------------------------------------------------------------------------
# Exposure Structs & Aggregation Functions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrikeExposure:
    """Detailed Greek exposures for a single strike across calls and puts."""
    strike: float
    call_oi: int
    put_oi: int
    call_volume: int
    put_volume: int
    call_iv: float | None
    put_iv: float | None
    call_gamma: float
    put_gamma: float
    call_gex_m: float  # $ Millions per 1% spot move
    put_gex_m: float   # $ Millions per 1% spot move
    net_gex_m: float   # Net Dealer GEX ($M)
    call_vex_m: float  # Vanna exposure ($M per 1% IV shift)
    put_vex_m: float
    net_vex_m: float
    call_chex_m: float # Charm exposure ($M per day)
    put_chex_m: float
    net_chex_m: float
    speed_m: float     # Speed ($M per 1% spot move / $ spot)
    zomma_m: float     # Zomma ($M per 1% spot move / 1% IV)


@dataclass(frozen=True)
class TopographyState:
    """Topographical classification of dealer gamma surface."""
    quadrant: str  # "forward_positive_ramp" | "backward_positive_ramp" | "forward_negative_slide" | "backward_negative_slide"
    title: str
    description: str
    dealer_hedging_action: str
    expected_market_behavior: str
    gex_above_spot_m: float
    gex_below_spot_m: float
    gex_ratio: float
    call_wall: float
    put_wall: float
    gamma_flip: float
    volatility_trigger: float
    absolute_gamma_peak: float


@dataclass(frozen=True)
class MicrostructureRegimeSnapshot:
    """Unified snapshot of microstructure regime dynamics."""
    symbol: str
    spot: float
    asof: str
    regime: str  # "positive_gamma" | "negative_gamma" | "neutral_transition"
    regime_confidence: float  # 0.0 to 1.0
    net_gex_m: float
    call_gex_m: float
    put_gex_m: float
    net_vex_m: float
    net_chex_m: float
    hedging_flow_m: float  # Instantaneous F_hedge ($M)
    zero_dte_charm_drift_m: float # Expected 0DTE afternoon charm drift ($M)
    gamma_flip: float
    call_wall: float
    put_wall: float
    volatility_trigger: float
    absolute_gamma_peak: float
    topography: TopographyState
    strikes: list[StrikeExposure]
    synthetic_gex_profile: list[dict[str, float]]  # Spot vs Net GEX curve
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Exposure & Surface Profile Calculations
# ---------------------------------------------------------------------------

def calculate_contract_gex(
    *,
    open_interest: float,
    gamma: float,
    spot: float,
    multiplier: float = 100.0,
) -> float:
    """Dollar Gamma Exposure per 1% underlying move: OI * M * Gamma * S^2 * 0.01."""
    if open_interest <= 0 or gamma <= 0 or spot <= 0:
        return 0.0
    return open_interest * multiplier * gamma * (spot ** 2) * 0.01


def calculate_contract_vex(
    *,
    open_interest: float,
    vanna: float,
    spot: float,
    multiplier: float = 100.0,
) -> float:
    """Dollar Vanna Exposure per 1% IV move: OI * M * Vanna * S * 0.01."""
    if open_interest <= 0 or spot <= 0:
        return 0.0
    return open_interest * multiplier * vanna * spot * 0.01


def calculate_contract_chex(
    *,
    open_interest: float,
    charm: float,
    spot: float,
    multiplier: float = 100.0,
) -> float:
    """Dollar Charm Exposure per calendar day: OI * M * Charm * S."""
    if open_interest <= 0 or spot <= 0:
        return 0.0
    return open_interest * multiplier * charm * spot


def compute_microstructure_regime(
    chain_rows: Sequence[Mapping[str, Any]],
    *,
    symbol: str = "SPY",
    spot: float,
    rate: float = _DEFAULT_RATE,
    asof: str = "",
    is_index: bool = True,
    ds_dt_pct: float = 0.0,    # Daily spot return rate (e.g. +0.01 = +1%)
    dvol_dt_pct: float = 0.0,  # Daily IV change rate (e.g. -0.02 = -2% IV)
) -> MicrostructureRegimeSnapshot:
    """Build a comprehensive Microstructure Regime Snapshot from normalized options chain data.

    Args:
        chain_rows: Sequence of normalized option chain dictionaries with keys:
            strike, right ('call'/'put'), open_interest, volume, dte/years, implied_volatility.
        symbol: Underlier ticker.
        spot: Live spot price.
        rate: Risk-free rate.
        asof: Timestamp string.
        is_index: True for broad market index complexes (dealers long calls, short puts);
                  False for single-stock speculative setups (dealers short calls, short puts).
        ds_dt_pct: Instantaneous spot price velocity (1.0 = +100%, 0.01 = +1%).
        dvol_dt_pct: Instantaneous IV velocity.

    Returns:
        MicrostructureRegimeSnapshot with complete Greeks, topography, and structural levels.
    """
    if spot <= 0:
        raise ValueError("spot must be positive")

    # Dealer sign conventions:
    # Under index convention:
    #   Customers buy puts (dealer short puts -> dealer put gamma sign = -1)
    #   Customers sell calls (dealer long calls -> dealer call gamma sign = +1)
    # Under speculative equity convention:
    #   Customers buy calls (dealer short calls -> dealer call gamma sign = -1)
    #   Customers buy puts (dealer short puts -> dealer put gamma sign = -1)
    phi_call = 1.0 if is_index else -1.0
    phi_put = -1.0

    # Group contracts by strike
    strike_map: dict[float, dict[str, Any]] = {}
    zero_dte_put_chex_total = 0.0

    for row in chain_rows:
        try:
            strike = float(row.get("strike") or 0.0)
            if strike <= 0:
                continue
            right = str(row.get("right") or row.get("side") or "").strip().lower()
            if not right:
                continue
            right_norm = "call" if right in {"c", "call", "calls"} else "put" if right in {"p", "put", "puts"} else None
            if right_norm is None:
                continue

            oi = int(float(row.get("open_interest") or row.get("oi") or 0))
            vol = int(float(row.get("volume") or row.get("vol") or 0))
            iv = float(row.get("implied_volatility") or row.get("iv") or 0.0)
            dte = float(row.get("dte") or 0.0)
            years = float(row.get("years") or (dte / 365.25) or 0.0)
            if years <= 0 and dte <= 0:
                # 0DTE contract
                years = 0.5 / 365.25  # Half day for Greek evaluation

            if strike not in strike_map:
                strike_map[strike] = {
                    "strike": strike,
                    "call_oi": 0,
                    "put_oi": 0,
                    "call_vol": 0,
                    "put_vol": 0,
                    "call_iv": None,
                    "put_iv": None,
                    "call_years": years,
                    "put_years": years,
                    "call_greeks": None,
                    "put_greeks": None,
                    "is_0dte": (dte <= 1),
                }

            entry = strike_map[strike]
            if right_norm == "call":
                entry["call_oi"] += oi
                entry["call_vol"] += vol
                if _MIN_IV <= iv <= _MAX_IV:
                    entry["call_iv"] = iv
                    entry["call_years"] = years
            else:
                entry["put_oi"] += oi
                entry["put_vol"] += vol
                if _MIN_IV <= iv <= _MAX_IV:
                    entry["put_iv"] = iv
                    entry["put_years"] = years

        except (TypeError, ValueError):
            continue

    # Compute Greeks and exposures per strike
    strike_exposures: list[StrikeExposure] = []
    total_call_gex = 0.0
    total_put_gex = 0.0
    total_net_gex = 0.0
    total_call_vex = 0.0
    total_put_vex = 0.0
    total_net_vex = 0.0
    total_call_chex = 0.0
    total_put_chex = 0.0
    total_net_chex = 0.0

    sorted_strikes = sorted(strike_map.keys())
    for k in sorted_strikes:
        entry = strike_map[k]
        call_iv = entry["call_iv"] or 0.20
        put_iv = entry["put_iv"] or 0.20
        call_years = entry["call_years"] or (30.0 / 365.25)
        put_years = entry["put_years"] or (30.0 / 365.25)

        cg = calculate_option_greeks(
            spot=spot, strike=k, years=call_years, iv=call_iv, right="call", rate=rate
        )
        pg = calculate_option_greeks(
            spot=spot, strike=k, years=put_years, iv=put_iv, right="put", rate=rate
        )

        call_gamma = cg.gamma if cg else 0.0
        put_gamma = pg.gamma if pg else 0.0

        # Dollar GEX ($M)
        call_gex_raw = calculate_contract_gex(open_interest=entry["call_oi"], gamma=call_gamma, spot=spot)
        put_gex_raw = calculate_contract_gex(open_interest=entry["put_oi"], gamma=put_gamma, spot=spot)
        call_gex_m = (phi_call * call_gex_raw) / 1e6
        put_gex_m = (phi_put * put_gex_raw) / 1e6
        net_gex_m = call_gex_m + put_gex_m

        # Vanna ($M)
        call_vanna = cg.vanna if cg else 0.0
        put_vanna = pg.vanna if pg else 0.0
        call_vex_raw = calculate_contract_vex(open_interest=entry["call_oi"], vanna=call_vanna, spot=spot)
        put_vex_raw = calculate_contract_vex(open_interest=entry["put_oi"], vanna=put_vanna, spot=spot)
        call_vex_m = (phi_call * call_vex_raw) / 1e6
        put_vex_m = (phi_put * put_vex_raw) / 1e6
        net_vex_m = call_vex_m + put_vex_m

        # Charm ($M per day)
        call_charm = cg.charm if cg else 0.0
        put_charm = pg.charm if pg else 0.0
        call_chex_raw = calculate_contract_chex(open_interest=entry["call_oi"], charm=call_charm, spot=spot)
        put_chex_raw = calculate_contract_chex(open_interest=entry["put_oi"], charm=put_charm, spot=spot)
        call_chex_m = (phi_call * call_chex_raw) / 1e6
        put_chex_m = (phi_put * put_chex_raw) / 1e6
        net_chex_m = call_chex_m + put_chex_m

        # 0DTE Charm contribution
        if entry["is_0dte"] and k < spot:
            # Out-of-the-money 0DTE put decay forces dealer buying
            zero_dte_put_chex_total += abs(put_chex_m)

        # Speed & Zomma
        call_speed = cg.speed if cg else 0.0
        put_speed = pg.speed if pg else 0.0
        speed_raw = (entry["call_oi"] * call_speed + entry["put_oi"] * put_speed) * 100.0 * (spot ** 2) * 0.01
        speed_m = speed_raw / 1e6

        call_zomma = cg.zomma if cg else 0.0
        put_zomma = pg.zomma if pg else 0.0
        zomma_raw = (entry["call_oi"] * call_zomma + entry["put_oi"] * put_zomma) * 100.0 * (spot ** 2) * 0.01
        zomma_m = zomma_raw / 1e6

        total_call_gex += call_gex_m
        total_put_gex += put_gex_m
        total_net_gex += net_gex_m
        total_call_vex += call_vex_m
        total_put_vex += put_vex_m
        total_net_vex += net_vex_m
        total_call_chex += call_chex_m
        total_put_chex += put_chex_m
        total_net_chex += net_chex_m

        strike_exposures.append(
            StrikeExposure(
                strike=k,
                call_oi=entry["call_oi"],
                put_oi=entry["put_oi"],
                call_volume=entry["call_vol"],
                put_volume=entry["put_vol"],
                call_iv=entry["call_iv"],
                put_iv=entry["put_iv"],
                call_gamma=call_gamma,
                put_gamma=put_gamma,
                call_gex_m=round(call_gex_m, 4),
                put_gex_m=round(put_gex_m, 4),
                net_gex_m=round(net_gex_m, 4),
                call_vex_m=round(call_vex_m, 4),
                put_vex_m=round(put_vex_m, 4),
                net_vex_m=round(net_vex_m, 4),
                call_chex_m=round(call_chex_m, 4),
                put_chex_m=round(put_chex_m, 4),
                net_chex_m=round(net_chex_m, 4),
                speed_m=round(speed_m, 4),
                zomma_m=round(zomma_m, 4),
            )
        )

    # Compute Structural Boundaries
    if strike_exposures:
        call_wall = max(strike_exposures, key=lambda s: abs(s.call_gex_m)).strike
        put_wall = max(strike_exposures, key=lambda s: abs(s.put_gex_m)).strike
        volatility_trigger = max(strike_exposures, key=lambda s: abs(s.speed_m) + abs(s.zomma_m)).strike
        absolute_gamma_peak = max(strike_exposures, key=lambda s: abs(s.net_gex_m)).strike
    else:
        call_wall = spot * 1.05
        put_wall = spot * 0.95
        volatility_trigger = spot
        absolute_gamma_peak = spot

    # Synthetic GEX Curve across spot space to find precise Gamma Flip S*
    min_strike = sorted_strikes[0] if sorted_strikes else spot * 0.8
    max_strike = sorted_strikes[-1] if sorted_strikes else spot * 1.2
    test_spots = np.linspace(min_strike * 0.95, max_strike * 1.05, 50)
    synthetic_gex_profile: list[dict[str, float]] = []

    for s_test in test_spots:
        s_gex = 0.0
        for k in sorted_strikes:
            entry = strike_map[k]
            call_iv = entry["call_iv"] or 0.20
            put_iv = entry["put_iv"] or 0.20
            call_years = entry["call_years"] or (30.0 / 365.25)
            put_years = entry["put_years"] or (30.0 / 365.25)

            cg_test = calculate_option_greeks(spot=float(s_test), strike=k, years=call_years, iv=call_iv, right="call", rate=rate)
            pg_test = calculate_option_greeks(spot=float(s_test), strike=k, years=put_years, iv=put_iv, right="put", rate=rate)

            c_gamma = cg_test.gamma if cg_test else 0.0
            p_gamma = pg_test.gamma if pg_test else 0.0

            c_gex = calculate_contract_gex(open_interest=entry["call_oi"], gamma=c_gamma, spot=float(s_test))
            p_gex = calculate_contract_gex(open_interest=entry["put_oi"], gamma=p_gamma, spot=float(s_test))
            s_gex += (phi_call * c_gex + phi_put * p_gex) / 1e6

        synthetic_gex_profile.append({"spot": round(float(s_test), 2), "net_gex_m": round(s_gex, 4)})

    # Find Gamma Flip S* (root where Net GEX = 0)
    gamma_flip = spot
    found_flip = False
    for i in range(len(synthetic_gex_profile) - 1):
        p1 = synthetic_gex_profile[i]
        p2 = synthetic_gex_profile[i + 1]
        if (p1["net_gex_m"] <= 0 and p2["net_gex_m"] >= 0) or (p1["net_gex_m"] >= 0 and p2["net_gex_m"] <= 0):
            # Linear interpolation for zero crossing
            dy = p2["net_gex_m"] - p1["net_gex_m"]
            if abs(dy) > 1e-6:
                frac = (0.0 - p1["net_gex_m"]) / dy
                gamma_flip = p1["spot"] + frac * (p2["spot"] - p1["spot"])
                found_flip = True
                break

    if not found_flip:
        # Fallback to spot if completely positive or negative
        gamma_flip = spot if total_net_gex == 0 else (spot * 0.95 if total_net_gex > 0 else spot * 1.05)

    # Topography Quadrant Classification
    gex_above_spot = sum(s.net_gex_m for s in strike_exposures if s.strike >= spot)
    gex_below_spot = sum(s.net_gex_m for s in strike_exposures if s.strike < spot)
    denom_gex = max(abs(gex_below_spot), 1e-3)
    gex_ratio = gex_above_spot / denom_gex

    if spot >= gamma_flip:
        # Positive Gamma Region
        if gex_above_spot >= gex_below_spot:
            quadrant = "forward_positive_ramp"
            title = "Forward Positive Ramp"
            desc = "Large positive GEX stacked overhead above spot price."
            action = "Dealers sell aggressively into upward price progress."
            behavior = "Mean-reverting grind; upside progress decelerates into strong strike pins."
        else:
            quadrant = "backward_positive_ramp"
            title = "Backward Positive Ramp"
            desc = "Heavy positive GEX cushion positioned below spot; thin overhead resistance."
            action = "Downside breaks encounter massive dealer buying support."
            behavior = "Downside cushion with potential for rapid upward expansion once local friction clears."
    else:
        # Negative Gamma Region
        if gex_below_spot <= gex_above_spot:
            quadrant = "forward_negative_slide"
            title = "Forward Negative Slide"
            desc = "Deep negative GEX stacked below spot price."
            action = "Downward spot motion forces accelerating dealer short-selling."
            behavior = "Directional breakdown cascades; severe volatility expansion and liquidity voids."
        else:
            quadrant = "backward_negative_slide"
            title = "Backward Negative Slide"
            desc = "Deep negative GEX overhead with spot operating below the flip level."
            action = "Upward moves force rapid dealer short-covering and call hedging."
            behavior = "Violent short-squeeze dynamics; sharp, erratic recovery rallies."

    topography = TopographyState(
        quadrant=quadrant,
        title=title,
        description=desc,
        dealer_hedging_action=action,
        expected_market_behavior=behavior,
        gex_above_spot_m=round(gex_above_spot, 4),
        gex_below_spot_m=round(gex_below_spot, 4),
        gex_ratio=round(gex_ratio, 3),
        call_wall=round(call_wall, 2),
        put_wall=round(put_wall, 2),
        gamma_flip=round(gamma_flip, 2),
        volatility_trigger=round(volatility_trigger, 2),
        absolute_gamma_peak=round(absolute_gamma_peak, 2),
    )

    # Regime Determination
    neutral_threshold = 0.0025 * spot
    if abs(spot - gamma_flip) <= neutral_threshold or abs(total_net_gex) < 5.0:
        regime = "neutral_transition"
        confidence = 0.65
    elif total_net_gex > 0 and spot > gamma_flip:
        regime = "positive_gamma"
        confidence = min(0.98, 0.70 + (total_net_gex / 500.0))
    else:
        regime = "negative_gamma"
        confidence = min(0.98, 0.70 + (abs(total_net_gex) / 500.0))

    # Total Instantaneous Hedging Flow ($M)
    # F_hedge = GEX_net * (dS/dt) + VEX_net * (dSigma/dt) + CHEX_net
    # Note: ds_dt_pct is in %, so GEX ($M per 1%) * ds_dt_pct gives $M flow.
    hedging_flow_m = (total_net_gex * (ds_dt_pct * 100.0)) + (total_net_vex * (dvol_dt_pct * 100.0)) + total_net_chex

    notes = [
        f"Gamma Flip Level: ${gamma_flip:.2f} (Spot is {'above' if spot >= gamma_flip else 'below'} flip)",
        f"Call Wall resistance at ${call_wall:.2f}, Put Wall support at ${put_wall:.2f}",
        f"Topography: {title} ({behavior})",
    ]
    if zero_dte_put_chex_total > 1.0:
        notes.append(f"0DTE Charm decay provides ${zero_dte_put_chex_total:.2f}M afternoon unhedging tailwind")

    return MicrostructureRegimeSnapshot(
        symbol=symbol,
        spot=round(spot, 2),
        asof=asof,
        regime=regime,
        regime_confidence=round(confidence, 3),
        net_gex_m=round(total_net_gex, 4),
        call_gex_m=round(total_call_gex, 4),
        put_gex_m=round(total_put_gex, 4),
        net_vex_m=round(total_net_vex, 4),
        net_chex_m=round(total_net_chex, 4),
        hedging_flow_m=round(hedging_flow_m, 4),
        zero_dte_charm_drift_m=round(zero_dte_put_chex_total, 4),
        gamma_flip=round(gamma_flip, 2),
        call_wall=round(call_wall, 2),
        put_wall=round(put_wall, 2),
        volatility_trigger=round(volatility_trigger, 2),
        absolute_gamma_peak=round(absolute_gamma_peak, 2),
        topography=topography,
        strikes=strike_exposures,
        synthetic_gex_profile=synthetic_gex_profile,
        notes=notes,
    )
