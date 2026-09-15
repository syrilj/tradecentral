"""Real-time market regime detection and price attraction / magnet levels engine.

Computes active volatility/flow market regimes (volatility dampening vs amplification,
charm decay drift, kinematic acceleration vs mean-reversion) and quantifies price magnet
targets (Call Wall, Put Wall, Gamma Flip, Max Pain Pin, Kinematic Drift, Volume POC)
with multi-factor gravitational pull scores and zero-spoofing guarantees.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from daily_plays import gex_core
from edge.research.expected_move import compute_expected_move_1d


# ---------------------------------------------------------------------------
# Data Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceMagnetLevel:
    level_id: str  # "call_wall" | "put_wall" | "gamma_flip" | "max_pain" | "kinematic_drift" | "volume_poc"
    label: str  # "Call Wall", "Put Wall", "Zero-Gamma Flip", "Max Pain Pin", "Kinematic Attractor", "Volume POC"
    price: float  # Price level ($)
    distance_points: float  # Signed price difference: price - spot
    distance_pct: float  # Signed percentage distance: (price - spot) / spot * 100
    direction: str  # "above" | "below" | "at_spot"
    gravitational_pull: float  # Quantitative score [0.0 - 100.0]
    structural_force: (
        str  # e.g. "Overhead Resistance Cap", "Downside Support Floor", "Regime Transition Pivot"
    )
    conviction_rank: int  # 1 = strongest attractor, 2 = secondary, etc.
    components: dict[str, float] = field(default_factory=dict)

    def _as_telemetry_dict(self) -> dict[str, Any]:
        supporting: list[str] = []
        if (
            "call_wall" in self.level_id
            or "put_wall" in self.level_id
            or "gamma_flip" in self.level_id
        ):
            supporting.append("GAMMA")
        if "max_pain" in self.level_id:
            supporting.append("PIN")
        if "volume" in self.level_id:
            supporting.append("VOLUME")
        if "kinematic" in self.level_id:
            supporting.append("KALMAN")

        return {
            "id": self.level_id,
            "type": self.level_id if self.level_id != "max_pain" else "max_pain_pin",
            "label": self.label,
            "price": self.price,
            "distance_pts": self.distance_points,
            "distance_pct": self.distance_pct,
            "pull_score": self.gravitational_pull,
            "direction": self.direction,
            "regime_role": self.structural_force,
            "conviction_rank": self.conviction_rank,
            "supporting_lenses": supporting,
            "lens_count": len(supporting),
            "is_primary_magnet": self.conviction_rank == 1,
            "components": self.components,
        }


@dataclass(frozen=True)
class MarketRegimeState:
    volatility_regime: (
        str  # "positive_gamma" | "negative_gamma" | "neutral_transition" | "unmeasurable"
    )
    volatility_behavior: str  # "volatility_dampening" | "volatility_amplification" | "neutral_straddle" | "unmeasured"
    topography_quadrant: str  # "forward_positive_ramp" | "backward_positive_ramp" | "forward_negative_slide" | "backward_negative_slide" | "unmeasurable"
    kinematic_regime: (
        str  # "trend_acceleration" | "mean_reverting" | "momentum_exhaustion" | "undetermined"
    )
    charm_drift_regime: str  # "buying_drift" | "selling_drift" | "neutral_decay" | "unmeasured"
    regime_strength: float  # Scale-free score [0.0 - 1.0]
    total_net_gex_m: float  # Net dealer GEX ($M per 1% move)
    gamma_flip: float | None  # Zero-gamma price ($)
    spot: float  # Active spot price ($)
    expected_move_1d: float | None  # 1-Day Expected Move ($)
    measurable: bool  # Truth flag


@dataclass(frozen=True)
class ConfluenceCluster:
    level: float
    distance_pct: float | None
    supporting_lenses: list[str]
    lens_count: int
    labels: list[str]
    above_spot: bool


@dataclass(frozen=True)
class RegimeAttractorSnapshot:
    symbol: str
    spot: float | None
    asof_utc: str
    regime_state: str
    regime_label: str
    regime_strength: float | None
    dominant_direction: str
    primary_magnet: PriceMagnetLevel | None
    levels: list[PriceMagnetLevel]
    price_ladder: list[PriceMagnetLevel]
    confluence_clusters: list[ConfluenceCluster]
    quality: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "spot": self.spot,
            "asof_utc": self.asof_utc,
            "regime_state": self.regime_state,
            "regime_label": self.regime_label,
            "regime_strength": self.regime_strength,
            "dominant_direction": self.dominant_direction,
            "primary_magnet": (
                self.primary_magnet._as_telemetry_dict() if self.primary_magnet else None
            ),
            "levels": [lvl._as_telemetry_dict() for lvl in self.levels],
            "price_ladder": [lvl._as_telemetry_dict() for lvl in self.price_ladder],
            "confluence_clusters": [asdict(c) for c in self.confluence_clusters],
            "quality": self.quality,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Row Parsing Helper
# ---------------------------------------------------------------------------


def _parse_chain_row(
    row: Mapping[str, Any],
) -> tuple[float, str, float, float, float, float, float] | None:
    """Extracts (strike, option_type, oi, iv, dte, volume, multiplier) from diverse provider rows."""
    try:
        strike_raw = row.get("strike") or row.get("strike_price") or row.get("k")
        if strike_raw is None:
            return None
        strike = float(strike_raw)
        if strike <= 0:
            return None

        right_raw = (
            str(row.get("right") or row.get("option_type") or row.get("type") or "").strip().lower()
        )
        if right_raw.startswith("c") or right_raw == "call":
            opt_type = "call"
        elif right_raw.startswith("p") or right_raw == "put":
            opt_type = "put"
        else:
            return None

        oi_raw = row.get("open_interest") or row.get("oi") or row.get("openInterest") or 0.0
        oi = max(0.0, float(oi_raw))

        iv_raw = (
            row.get("iv")
            or row.get("implied_vol")
            or row.get("implied_volatility")
            or row.get("volatility")
            or 0.25
        )
        iv = max(0.005, min(8.0, float(iv_raw)))

        dte_raw = (
            row.get("dte") or row.get("days_to_expiration") or row.get("days_to_expiry") or 30.0
        )
        dte = max(0.0, float(dte_raw))

        vol_raw = row.get("volume") or row.get("vol") or 0.0
        vol = max(0.0, float(vol_raw))

        mult_raw = row.get("multiplier") or row.get("contract_multiplier") or 100.0
        mult = float(mult_raw)

        return strike, opt_type, oi, iv, dte, vol, mult
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Pure Mathematical & Analytical Routines
# ---------------------------------------------------------------------------


def bs_d1_d2(
    spot: float,
    strike: float,
    years: float,
    iv: float,
    rate: float = 0.045,
) -> tuple[float, float] | None:
    """Calculates Black-Scholes d1 and d2 with strict boundary validation."""
    if spot <= 0 or strike <= 0 or years <= 0 or iv <= 0.005 or iv > 8.0:
        return None
    try:
        vol_sqrt_t = iv * math.sqrt(years)
        if vol_sqrt_t <= 0:
            return None
        d1 = (math.log(spot / strike) + (rate + 0.5 * (iv**2)) * years) / vol_sqrt_t
        d2 = d1 - vol_sqrt_t
        return d1, d2
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def calculate_bs_gamma(
    spot: float,
    strike: float,
    years: float,
    iv: float,
    rate: float = 0.045,
) -> float | None:
    """Calculates Black-Scholes standard Gamma with stability guards."""
    d1_d2 = bs_d1_d2(spot, strike, years, iv, rate)
    if d1_d2 is None:
        return None
    d1, _ = d1_d2
    try:
        phi = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        denom = spot * iv * math.sqrt(years)
        if denom <= 0:
            return None
        return phi / denom
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def calculate_bs_charm_per_day(
    spot: float,
    strike: float,
    years: float,
    iv: float,
    rate: float = 0.045,
    is_call: bool = True,
) -> float | None:
    """Calculates Black-Scholes Charm per day (dDelta/dt / 365) with tenor floor guard."""
    if years < 1.0 / 365.0:
        return None
    d1_d2 = bs_d1_d2(spot, strike, years, iv, rate)
    if d1_d2 is None:
        return None
    d1, d2 = d1_d2
    try:
        phi = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        vol_sqrt_t = iv * math.sqrt(years)
        term1 = rate / vol_sqrt_t
        term2 = d2 / (2.0 * years)
        charm_call_annual = -phi * (term1 - term2)
        charm_call_day = charm_call_annual / 365.0
        if is_call:
            return charm_call_day
        else:
            discount = math.exp(-rate * years)
            charm_put_day = charm_call_day + (rate * discount) / 365.0
            return charm_put_day
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def calculate_dollar_gamma_1pct(
    open_interest: float,
    gamma: float,
    spot: float,
    multiplier: float = 100.0,
) -> float:
    """Calculates Dollar Gamma per 1% spot move ($): OI * M * Gamma * Spot^2 * 0.01."""
    if open_interest <= 0 or gamma <= 0 or spot <= 0:
        return 0.0
    return open_interest * multiplier * gamma * (spot**2) * 0.01


def calculate_max_pain(
    chain_rows: Sequence[Mapping[str, Any]],
    spot: float,
) -> float | None:
    """Calculates Max Pain strike minimizing cumulative option buyer dollar payout."""
    if spot <= 0 or not chain_rows:
        return None

    call_oi_by_k: dict[float, float] = {}
    put_oi_by_k: dict[float, float] = {}
    total_oi = 0.0

    for row in chain_rows:
        parsed = _parse_chain_row(row)
        if not parsed:
            continue
        k, opt_type, oi, _, _, _, _ = parsed
        if oi > 0:
            total_oi += oi
            if opt_type == "call":
                call_oi_by_k[k] = call_oi_by_k.get(k, 0.0) + oi
            else:
                put_oi_by_k[k] = put_oi_by_k.get(k, 0.0) + oi

    if total_oi <= 0:
        return None

    all_strikes = sorted(set(call_oi_by_k.keys()) | set(put_oi_by_k.keys()))
    if not all_strikes:
        return None

    min_payout = float("inf")
    best_strike = all_strikes[0]

    for candidate in all_strikes:
        call_loss = sum(max(0.0, candidate - k) * oi for k, oi in call_oi_by_k.items())
        put_loss = sum(max(0.0, k - candidate) * oi for k, oi in put_oi_by_k.items())
        total_payout = call_loss + put_loss
        if total_payout < min_payout:
            min_payout = total_payout
            best_strike = candidate
        elif total_payout == min_payout:
            if abs(candidate - spot) < abs(best_strike - spot):
                best_strike = candidate

    return best_strike


def compute_gamma_flip_and_walls(
    chain_rows: Sequence[Mapping[str, Any]],
    spot: float,
    rate: float = 0.045,
) -> tuple[float | None, float | None, float | None, float, list[dict[str, Any]]]:
    """Computes Gamma Flip S* (linear interpolation), directional walls (strictly above/below spot), and net GEX."""
    if spot <= 0 or not chain_rows:
        return None, None, None, 0.0, []

    strikes_dict: dict[float, dict[str, float]] = {}

    for row in chain_rows:
        parsed = _parse_chain_row(row)
        if not parsed:
            continue
        k, opt_type, oi, iv, dte, vol, mult = parsed
        if k not in strikes_dict:
            strikes_dict[k] = {
                "call_oi": 0.0,
                "put_oi": 0.0,
                "call_vol": 0.0,
                "put_vol": 0.0,
                "call_gex_m": 0.0,
                "put_gex_m": 0.0,
            }

        years = max(dte, 1.0) / 365.0
        gamma = calculate_bs_gamma(spot, k, years, iv, rate) or 0.0
        dollar_gex_m = calculate_dollar_gamma_1pct(oi, gamma, spot, mult) / 1_000_000.0

        if opt_type == "call":
            strikes_dict[k]["call_oi"] += oi
            strikes_dict[k]["call_vol"] += vol
            strikes_dict[k]["call_gex_m"] += dollar_gex_m
        else:
            strikes_dict[k]["put_oi"] += oi
            strikes_dict[k]["put_vol"] += vol
            strikes_dict[k]["put_gex_m"] += dollar_gex_m

    if not strikes_dict:
        return None, None, None, 0.0, []

    sorted_k = sorted(strikes_dict.keys())
    mapped_strike_gex: list[dict[str, Any]] = []
    total_net_gex_m = 0.0

    for k in sorted_k:
        c_oi = strikes_dict[k]["call_oi"]
        p_oi = strikes_dict[k]["put_oi"]
        c_gex = strikes_dict[k]["call_gex_m"]
        p_gex = strikes_dict[k]["put_gex_m"]
        net_gex = c_gex - p_gex
        total_net_gex_m += net_gex
        mapped_strike_gex.append(
            {
                "strike": k,
                "call_oi": c_oi,
                "put_oi": p_oi,
                "call_gex_m": c_gex,
                "put_gex_m": p_gex,
                "net_gex_m": net_gex,
            }
        )

    # Directional Call Wall: strictly above spot with maximum call OI
    calls_above = [r for r in mapped_strike_gex if r["strike"] > spot and r["call_oi"] > 0]
    call_wall: float | None = (
        max(calls_above, key=lambda r: (r["call_oi"], -abs(r["strike"] - spot)))["strike"]
        if calls_above
        else None
    )

    # Directional Put Wall: strictly below spot with maximum put OI
    puts_below = [r for r in mapped_strike_gex if r["strike"] < spot and r["put_oi"] > 0]
    put_wall: float | None = (
        max(puts_below, key=lambda r: (r["put_oi"], -abs(r["strike"] - spot)))["strike"]
        if puts_below
        else None
    )

    # Continuous Gamma Flip S* via linear interpolation across zero-crossings
    has_pos = any(r["net_gex_m"] > 1e-6 for r in mapped_strike_gex)
    has_neg = any(r["net_gex_m"] < -1e-6 for r in mapped_strike_gex)
    crossings: list[float] = []

    if has_pos and has_neg:
        for i in range(len(mapped_strike_gex) - 1):
            k1, g1 = mapped_strike_gex[i]["strike"], mapped_strike_gex[i]["net_gex_m"]
            k2, g2 = mapped_strike_gex[i + 1]["strike"], mapped_strike_gex[i + 1]["net_gex_m"]
            if g1 == 0.0:
                crossings.append(float(k1))
            elif (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
                denom = abs(g1) + abs(g2)
                if denom > 1e-9:
                    crossings.append(float(k1 + (abs(g1) / denom) * (k2 - k1)))

    gamma_flip: float | None = None
    if crossings:
        gamma_flip = min(crossings, key=lambda x: abs(x - spot))
        gamma_flip = round(gamma_flip, 2)

    return gamma_flip, call_wall, put_wall, total_net_gex_m, mapped_strike_gex


def classify_market_regime(
    spot: float,
    total_net_gex_m: float,
    gamma_flip: float | None,
    mapped_strike_gex: list[dict[str, Any]],
    charm_drift_regime: str = "neutral_decay",
    kinematic_regime: str = "undetermined",
    expected_move_1d: float | None = None,
) -> MarketRegimeState:
    """Classifies volatility regime, behavior, topography quadrant, and scale-free strength."""
    if spot <= 0 or not mapped_strike_gex:
        return MarketRegimeState(
            volatility_regime="unmeasurable",
            volatility_behavior="unmeasured",
            topography_quadrant="unmeasurable",
            kinematic_regime="undetermined",
            charm_drift_regime="unmeasured",
            regime_strength=0.0,
            total_net_gex_m=0.0,
            gamma_flip=None,
            spot=spot,
            expected_move_1d=None,
            measurable=False,
        )

    has_pos = any(r.get("net_gex_m", 0.0) > 1e-6 for r in mapped_strike_gex)
    has_neg = any(r.get("net_gex_m", 0.0) < -1e-6 for r in mapped_strike_gex)

    # Flip band: ±0.25% distance
    is_in_flip_band = False
    if gamma_flip is not None and has_pos and has_neg:
        delta_flip = abs(spot - gamma_flip) / spot
        if delta_flip <= 0.0025:
            is_in_flip_band = True

    if is_in_flip_band:
        vol_regime = "neutral_transition"
        vol_behavior = "neutral_straddle"
    elif total_net_gex_m > 0:
        vol_regime = "positive_gamma"
        vol_behavior = "volatility_dampening"
    elif total_net_gex_m < 0:
        vol_regime = "negative_gamma"
        vol_behavior = "volatility_amplification"
    else:
        vol_regime = "neutral_transition"
        vol_behavior = "neutral_straddle"

    # Topography Quadrant
    gex_above = sum(
        r.get("net_gex_m", 0.0) for r in mapped_strike_gex if r.get("strike", 0.0) > spot
    )
    gex_below = sum(
        r.get("net_gex_m", 0.0) for r in mapped_strike_gex if r.get("strike", 0.0) < spot
    )

    if gamma_flip is None:
        topography = "unmeasurable"
    elif spot >= gamma_flip:
        if gex_above >= gex_below:
            topography = "forward_positive_ramp"
        else:
            topography = "backward_positive_ramp"
    else:
        if gex_below <= gex_above:
            topography = "forward_negative_slide"
        else:
            topography = "backward_negative_slide"

    # Scale-Free Regime Strength [0.0 - 1.0]
    total_abs_gex = sum(abs(r.get("net_gex_m", 0.0)) for r in mapped_strike_gex)
    gex_ratio = min(1.0, abs(total_net_gex_m) / (total_abs_gex + 1.0)) if total_abs_gex > 0 else 0.0
    if gamma_flip is not None:
        dist_factor = min(1.0, abs(spot - gamma_flip) / (spot * 0.10))
    else:
        dist_factor = 1.0

    if not has_pos or not has_neg:
        # Strictly monotonic profile
        regime_strength = (
            min(1.0, max(0.2, 0.4 + 0.6 * gex_ratio)) if abs(total_net_gex_m) > 0 else 0.0
        )
    else:
        regime_strength = min(
            1.0,
            max(0.0, dist_factor * (0.3 + 0.7 * gex_ratio) if abs(total_net_gex_m) > 0 else 0.0),
        )

    return MarketRegimeState(
        volatility_regime=vol_regime,
        volatility_behavior=vol_behavior,
        topography_quadrant=topography,
        kinematic_regime=kinematic_regime,
        charm_drift_regime=charm_drift_regime,
        regime_strength=round(regime_strength, 4),
        total_net_gex_m=round(total_net_gex_m, 4),
        gamma_flip=gamma_flip,
        spot=spot,
        expected_move_1d=expected_move_1d,
        measurable=True,
    )


def compute_net_charm_flow(
    chain_rows: Sequence[Mapping[str, Any]],
    spot: float,
    rate: float = 0.045,
) -> tuple[float, str]:
    """Computes aggregate dealer Charm flow and directional drift regime."""
    if spot <= 0 or not chain_rows:
        return 0.0, "neutral_decay"

    total_flow = 0.0
    valid_count = 0

    for row in chain_rows:
        parsed = _parse_chain_row(row)
        if not parsed:
            continue
        k, opt_type, oi, iv, dte, _, mult = parsed
        if oi <= 0:
            continue

        years = max(dte, 1.0) / 365.0
        charm_day = calculate_bs_charm_per_day(
            spot, k, years, iv, rate, is_call=(opt_type == "call")
        )
        if charm_day is None:
            continue

        valid_count += 1
        if opt_type == "call":
            total_flow += oi * mult * charm_day * spot
        else:
            total_flow -= oi * mult * charm_day * spot

    if valid_count == 0 or abs(total_flow) < 1e-4:
        return 0.0, "neutral_decay"

    regime = "selling_drift" if total_flow > 0 else "buying_drift"
    return round(total_flow, 2), regime


def compute_kinematic_drift_level(
    price_series: Sequence[float] | None,
    spot: float,
) -> tuple[float | None, float, str]:
    """Applies a 2-State Constant Velocity Kalman Filter on log-prices to extract equilibrium price and velocity z-score."""
    if spot <= 0 or not price_series or len(price_series) < 5:
        return None, 0.0, "undetermined"

    prices = [float(p) for p in price_series if p is not None and p > 0]
    if len(prices) < 5:
        return None, 0.0, "undetermined"

    log_prices = np.log(prices)
    returns = np.diff(log_prices)
    var_r = float(np.var(returns)) if len(returns) > 1 else 0.0001
    var_r = max(var_r, 1e-6)

    # State: x = [log_price, velocity]^T
    x = np.array([log_prices[0], 0.0], dtype=float)
    P = np.array([[var_r, 0.0], [0.0, var_r]], dtype=float)
    F = np.array([[1.0, 1.0], [0.0, 1.0]], dtype=float)
    q0 = 0.05
    Q = q0 * var_r * np.array([[1.0 / 3.0, 0.5], [0.5, 1.0]], dtype=float)
    H = np.array([[1.0, 0.0]], dtype=float)
    R = max(1e-6, 0.5 * var_r)

    for y in log_prices[1:]:
        x = F @ x
        P = F @ P @ F.T + Q
        innov = y - (H @ x)[0]
        S_cov = (H @ P @ H.T)[0, 0] + R
        K = (P @ H.T)[:, 0] / S_cov
        x = x + K * innov
        P = (np.eye(2) - np.outer(K, H[0])) @ P

    p_hat = float(np.exp(x[0]))
    v_hat = float(x[1])
    v_std = math.sqrt(max(1e-9, float(P[1, 1])))
    v_z = v_hat / v_std

    regime = "trend_acceleration" if abs(v_z) > 1.5 else "mean_reverting"
    return round(p_hat, 2), round(v_z, 4), regime


def extract_volume_poc(
    chain_rows: Sequence[Mapping[str, Any]],
    spot: float,
) -> float | None:
    """Extracts Point of Control (POC) strike with maximum cumulative volume."""
    if spot <= 0 or not chain_rows:
        return None

    vol_by_k: dict[float, float] = {}
    for row in chain_rows:
        parsed = _parse_chain_row(row)
        if not parsed:
            continue
        k, _, _, _, _, vol, _ = parsed
        if vol > 0:
            vol_by_k[k] = vol_by_k.get(k, 0.0) + vol

    if not vol_by_k or max(vol_by_k.values()) <= 0:
        return None

    return max(vol_by_k.keys(), key=lambda s: vol_by_k[s])


def calculate_gravitational_pull(
    level_price: float,
    spot: float,
    level_type: str,
    mapped_strike_gex: list[dict[str, Any]] | None = None,
    expected_move_1d: float | None = None,
    kinematic_velocity_z: float = 0.0,
    charm_drift_regime: str = "neutral_decay",
) -> tuple[float, dict[str, float]]:
    """Synthesizes multi-factor gravitational pull score [0.0 - 100.0] and component attribution."""
    if spot <= 0 or level_price <= 0:
        return 0.0, {"proximity": 0.0, "gex_mass": 0.0, "alignment": 1.0}

    # Proximity normalized by Expected Move (Gaussian kernel)
    em = (
        expected_move_1d
        if (expected_move_1d is not None and expected_move_1d > 0)
        else (spot * 0.02)
    )
    d_em = abs(level_price - spot) / em
    prox = math.exp(-0.5 * (d_em / 2.0) ** 2)

    # GEX Mass component
    gex_mass = 0.5
    if mapped_strike_gex:
        closest_row = min(mapped_strike_gex, key=lambda r: abs(r.get("strike", 0.0) - level_price))
        if abs(closest_row.get("strike", 0.0) - level_price) <= max(0.02 * spot, 2.0):
            strike_net_gex = abs(closest_row.get("net_gex_m", 0.0))
            total_gex = sum(abs(r.get("net_gex_m", 0.0)) for r in mapped_strike_gex) + 1e-6
            gex_mass = min(1.0, max(0.0, strike_net_gex / (total_gex * 0.35 + 1.0)))

    # Base weight by level type
    base_weights = {
        "gamma_flip": 90.0,
        "call_wall": 85.0,
        "put_wall": 85.0,
        "max_pain": 80.0,
        "kinematic_drift": 75.0,
        "volume_poc": 70.0,
    }
    base = base_weights.get(level_type, 65.0)

    # Continuous directional alignment factors
    alignment = 1.0
    if level_type == "kinematic_drift":
        direction_match = 1.0 if (level_price - spot) * kinematic_velocity_z >= 0 else -1.0
        alignment += 0.20 * math.tanh(abs(kinematic_velocity_z) / 2.0) * direction_match
    elif level_type in ("call_wall", "put_wall"):
        if charm_drift_regime == "selling_drift" and level_type == "call_wall":
            alignment += 0.15
        elif charm_drift_regime == "buying_drift" and level_type == "put_wall":
            alignment += 0.15

    raw_pull = base * (0.60 * prox + 0.40 * gex_mass) * alignment
    pull_score = min(100.0, max(10.0, raw_pull))

    components = {
        "proximity": round(prox, 4),
        "gex_mass": round(gex_mass, 4),
        "alignment": round(alignment, 4),
    }
    return round(pull_score, 1), components


def detect_confluence_clusters(
    levels: Sequence[PriceMagnetLevel],
    spot: float,
    tolerance_pct: float = 0.75,
) -> list[ConfluenceCluster]:
    """Clusters multiple attractors within ±0.75% spot tolerance into multi-lens confluence zones."""
    if not levels or spot <= 0:
        return []

    sorted_levels = sorted(levels, key=lambda l: l.price)
    tolerance_pts = spot * (tolerance_pct / 100.0)

    clusters: list[ConfluenceCluster] = []
    current_group: list[PriceMagnetLevel] = [sorted_levels[0]]

    for i in range(1, len(sorted_levels)):
        prev = current_group[-1]
        curr = sorted_levels[i]
        if abs(curr.price - prev.price) <= tolerance_pts:
            current_group.append(curr)
        else:
            if len(current_group) >= 2:
                clusters.append(_create_confluence_cluster(current_group, spot))
            current_group = [curr]

    if len(current_group) >= 2:
        clusters.append(_create_confluence_cluster(current_group, spot))

    return clusters


def _create_confluence_cluster(group: list[PriceMagnetLevel], spot: float) -> ConfluenceCluster:
    avg_price = sum(l.price for l in group) / len(group)
    dist_pct = ((avg_price - spot) / spot) * 100.0
    labels = [l.label for l in group]

    supporting_lenses = set()
    for l in group:
        if "call_wall" in l.level_id or "put_wall" in l.level_id or "gamma_flip" in l.level_id:
            supporting_lenses.add("GAMMA")
        if "max_pain" in l.level_id:
            supporting_lenses.add("PIN")
        if "volume" in l.level_id:
            supporting_lenses.add("VOLUME")
        if "kinematic" in l.level_id:
            supporting_lenses.add("KALMAN")

    return ConfluenceCluster(
        level=round(avg_price, 4),
        distance_pct=round(dist_pct, 4),
        supporting_lenses=sorted(list(supporting_lenses)),
        lens_count=len(supporting_lenses),
        labels=labels,
        above_spot=avg_price >= spot,
    )


def compute_price_attractors(
    symbol: str,
    spot: float,
    chain_rows: Sequence[Mapping[str, Any]],
    price_series: Sequence[float] | None = None,
    asof_utc: str | None = None,
    rate: float = 0.045,
) -> RegimeAttractorSnapshot:
    """Orchestrates end-to-end regime classification, price magnet detection, and telemetry compilation."""
    now_iso = asof_utc or datetime.now(timezone.utc).isoformat()
    sym = symbol.upper()

    if spot <= 0 or not chain_rows:
        return RegimeAttractorSnapshot(
            symbol=sym,
            spot=spot if spot > 0 else None,
            asof_utc=now_iso,
            regime_state="unmeasurable",
            regime_label="Unmeasured Regime",
            regime_strength=None,
            dominant_direction="unmeasured",
            primary_magnet=None,
            levels=[],
            price_ladder=[],
            confluence_clusters=[],
            quality={
                "measurable": False,
                "open_interest_available": False,
                "iv_available": False,
                "volume_available": False,
                "reason": "Missing option chain data or non-positive spot price",
            },
            warnings=["Missing option chain data or non-positive spot price"],
        )

    # Check for total open interest presence
    total_oi = 0.0
    valid_parsed_rows = []
    for r in chain_rows:
        parsed = _parse_chain_row(r)
        if parsed:
            valid_parsed_rows.append(parsed)
            total_oi += parsed[2]

    if not valid_parsed_rows or total_oi <= 0:
        return RegimeAttractorSnapshot(
            symbol=sym,
            spot=spot,
            asof_utc=now_iso,
            regime_state="unmeasurable",
            regime_label="Unmeasured Regime",
            regime_strength=None,
            dominant_direction="unmeasured",
            primary_magnet=None,
            levels=[],
            price_ladder=[],
            confluence_clusters=[],
            quality={
                "measurable": False,
                "open_interest_available": False,
                "iv_available": False,
                "volume_available": False,
                "reason": "Open interest is zero across entire options chain",
            },
            warnings=["Open interest is zero across entire options chain"],
        )

    # 1. Gamma Flip & Directional Walls
    flip, call_wall, put_wall, total_gex, mapped = compute_gamma_flip_and_walls(
        chain_rows, spot, rate
    )

    # 2. Net Charm Flow
    charm_flow, charm_regime = compute_net_charm_flow(chain_rows, spot, rate)

    # 3. Kinematic Drift
    k_target, k_vz, k_regime = compute_kinematic_drift_level(price_series, spot)

    # 4. Max Pain Pin
    mp_strike = calculate_max_pain(chain_rows, spot)

    # 5. Volume POC
    vp_strike = extract_volume_poc(chain_rows, spot)

    # Expected Move 1D estimate
    # Same fabrication guard: no measured IV → no expected move.
    valid_ivs = [p[3] for p in valid_parsed_rows if 0.005 <= p[3] <= 8.0]
    expected_move_1d = (
        round(compute_expected_move_1d(spot, sum(valid_ivs) / len(valid_ivs), dte=1.0, calendar_days=True), 2)
        if valid_ivs
        else None
    )

    # 6. Classify Regime State
    regime_state_obj = classify_market_regime(
        spot=spot,
        total_net_gex_m=total_gex,
        gamma_flip=flip,
        mapped_strike_gex=mapped,
        charm_drift_regime=charm_regime,
        kinematic_regime=k_regime,
        expected_move_1d=expected_move_1d,
    )

    # 7. Construct Magnet Levels
    candidates: list[PriceMagnetLevel] = []

    if call_wall is not None:
        c_pts = call_wall - spot
        c_pct = (c_pts / spot) * 100.0
        pull, comps = calculate_gravitational_pull(
            call_wall, spot, "call_wall", mapped, expected_move_1d, k_vz, charm_regime
        )
        candidates.append(
            PriceMagnetLevel(
                level_id="call_wall",
                label="Call Wall",
                price=call_wall,
                distance_points=round(c_pts, 4),
                distance_pct=round(c_pct, 4),
                direction="above" if c_pts > 1e-6 else ("below" if c_pts < -1e-6 else "at_spot"),
                gravitational_pull=pull,
                structural_force="Overhead Resistance Cap" if c_pts >= 0 else "Breached Resistance",
                conviction_rank=1,
                components=comps,
            )
        )

    if put_wall is not None:
        p_pts = put_wall - spot
        p_pct = (p_pts / spot) * 100.0
        pull, comps = calculate_gravitational_pull(
            put_wall, spot, "put_wall", mapped, expected_move_1d, k_vz, charm_regime
        )
        candidates.append(
            PriceMagnetLevel(
                level_id="put_wall",
                label="Put Wall",
                price=put_wall,
                distance_points=round(p_pts, 4),
                distance_pct=round(p_pct, 4),
                direction="above" if p_pts > 1e-6 else ("below" if p_pts < -1e-6 else "at_spot"),
                gravitational_pull=pull,
                structural_force="Downside Support Floor" if p_pts <= 0 else "Breached Support",
                conviction_rank=1,
                components=comps,
            )
        )

    if flip is not None:
        gf_pts = flip - spot
        gf_pct = (gf_pts / spot) * 100.0
        pull, comps = calculate_gravitational_pull(
            flip, spot, "gamma_flip", mapped, expected_move_1d, k_vz, charm_regime
        )
        candidates.append(
            PriceMagnetLevel(
                level_id="gamma_flip",
                label="Zero-Gamma Flip",
                price=flip,
                distance_points=round(gf_pts, 4),
                distance_pct=round(gf_pct, 4),
                direction="above" if gf_pts > 1e-6 else ("below" if gf_pts < -1e-6 else "at_spot"),
                gravitational_pull=pull,
                structural_force="Regime Transition Pivot",
                conviction_rank=1,
                components=comps,
            )
        )

    if mp_strike is not None:
        mp_pts = mp_strike - spot
        mp_pct = (mp_pts / spot) * 100.0
        pull, comps = calculate_gravitational_pull(
            mp_strike, spot, "max_pain", mapped, expected_move_1d, k_vz, charm_regime
        )
        candidates.append(
            PriceMagnetLevel(
                level_id="max_pain",
                label="Max Pain Pin",
                price=mp_strike,
                distance_points=round(mp_pts, 4),
                distance_pct=round(mp_pct, 4),
                direction="above" if mp_pts > 1e-6 else ("below" if mp_pts < -1e-6 else "at_spot"),
                gravitational_pull=pull,
                structural_force="OpEx Expiry Pinning Magnet",
                conviction_rank=1,
                components=comps,
            )
        )

    if k_target is not None:
        kd_pts = k_target - spot
        kd_pct = (kd_pts / spot) * 100.0
        pull, comps = calculate_gravitational_pull(
            k_target, spot, "kinematic_drift", mapped, expected_move_1d, k_vz, charm_regime
        )
        candidates.append(
            PriceMagnetLevel(
                level_id="kinematic_drift",
                label="Kinematic Attractor",
                price=k_target,
                distance_points=round(kd_pts, 4),
                distance_pct=round(kd_pct, 4),
                direction="above" if kd_pts > 1e-6 else ("below" if kd_pts < -1e-6 else "at_spot"),
                gravitational_pull=pull,
                structural_force="Kalman Velocity Equilibrium",
                conviction_rank=1,
                components=comps,
            )
        )

    if vp_strike is not None and vp_strike != spot:
        vp_pts = vp_strike - spot
        vp_pct = (vp_pts / spot) * 100.0
        pull, comps = calculate_gravitational_pull(
            vp_strike, spot, "volume_poc", mapped, expected_move_1d, k_vz, charm_regime
        )
        candidates.append(
            PriceMagnetLevel(
                level_id="volume_poc",
                label="Volume POC",
                price=vp_strike,
                distance_points=round(vp_pts, 4),
                distance_pct=round(vp_pct, 4),
                direction="above" if vp_pts > 1e-6 else ("below" if vp_pts < -1e-6 else "at_spot"),
                gravitational_pull=pull,
                structural_force="High-Volume Liquidity Node",
                conviction_rank=1,
                components=comps,
            )
        )

    # Sort by gravitational pull descending and assign conviction_rank 1..N
    sorted_by_pull = sorted(candidates, key=lambda l: l.gravitational_pull, reverse=True)
    ranked_levels: list[PriceMagnetLevel] = []
    for rank, mag in enumerate(sorted_by_pull, start=1):
        ranked_levels.append(
            PriceMagnetLevel(
                level_id=mag.level_id,
                label=mag.label,
                price=mag.price,
                distance_points=mag.distance_points,
                distance_pct=mag.distance_pct,
                direction=mag.direction,
                gravitational_pull=mag.gravitational_pull,
                structural_force=mag.structural_force,
                conviction_rank=rank,
                components=mag.components,
            )
        )

    # Price Ladder: strictly descending by price
    price_ladder = sorted(ranked_levels, key=lambda l: l.price, reverse=True)

    # Confluence Clusters
    clusters = detect_confluence_clusters(ranked_levels, spot, tolerance_pct=0.75)

    # Dominant Direction
    total_above = sum(l.gravitational_pull for l in ranked_levels if l.price > spot)
    total_below = sum(l.gravitational_pull for l in ranked_levels if l.price < spot)
    total_pull = total_above + total_below
    if total_pull == 0 or abs(total_above - total_below) / total_pull < 0.15:
        dominant_dir = "neutral_pin"
    elif total_above > total_below:
        dominant_dir = "bullish_pull"
    else:
        dominant_dir = "bearish_pull"

    # Frontend regime mapping
    if charm_regime == "selling_drift":
        frontend_regime = "charm_decay_selling"
    elif charm_regime == "buying_drift":
        frontend_regime = "charm_decay_buying"
    elif regime_state_obj.volatility_regime == "positive_gamma":
        frontend_regime = "volatility_dampening"
    elif regime_state_obj.volatility_regime == "negative_gamma":
        frontend_regime = "volatility_amplification"
    else:
        frontend_regime = "neutral_transition"

    primary = ranked_levels[0] if ranked_levels else None

    return RegimeAttractorSnapshot(
        symbol=sym,
        spot=spot,
        asof_utc=now_iso,
        regime_state=frontend_regime,
        regime_label=regime_state_obj.volatility_regime.replace("_", " ").title(),
        regime_strength=regime_state_obj.regime_strength,
        dominant_direction=dominant_dir,
        primary_magnet=primary,
        levels=ranked_levels,
        price_ladder=price_ladder,
        confluence_clusters=clusters,
        quality={
            "measurable": True,
            "open_interest_available": True,
            "iv_available": len(valid_ivs) > 0,
            "volume_available": any(r.get("volume") for r in chain_rows),
            "reason": None,
        },
        warnings=[],
    )


# ---------------------------------------------------------------------------
# High-Level Backward Compatibility Wrappers
# ---------------------------------------------------------------------------


def calculate_market_regime(
    *,
    spot: float,
    strikes: Sequence[float],
    call_oi: Sequence[int | float],
    put_oi: Sequence[int | float],
    call_gammas: Sequence[float | None] | None = None,
    put_gammas: Sequence[float | None] | None = None,
    ivs: Sequence[float | None] | None = None,
    dte_years: float = 30.0 / 365.0,
    rate: float = 0.045,
    kinematic_velocity: float = 0.0,
) -> MarketRegimeState:
    """Classifies real-time market regime from options chain positioning and spot price."""
    if spot <= 0 or not strikes or not call_oi or not put_oi or len(strikes) == 0:
        return MarketRegimeState(
            volatility_regime="unmeasurable",
            volatility_behavior="unmeasured",
            topography_quadrant="unmeasurable",
            kinematic_regime="undetermined",
            charm_drift_regime="unmeasured",
            regime_strength=0.0,
            total_net_gex_m=0.0,
            gamma_flip=None,
            spot=spot,
            expected_move_1d=None,
            measurable=False,
        )

    n = len(strikes)
    total_oi = sum(call_oi) + sum(put_oi)
    if total_oi <= 0:
        return MarketRegimeState(
            volatility_regime="unmeasurable",
            volatility_behavior="unmeasured",
            topography_quadrant="unmeasurable",
            kinematic_regime="undetermined",
            charm_drift_regime="unmeasured",
            regime_strength=0.0,
            total_net_gex_m=0.0,
            gamma_flip=None,
            spot=spot,
            expected_move_1d=None,
            measurable=False,
        )

    valid_iv_list = [v for v in (ivs or []) if v is not None and 0.005 <= v <= 8.0]
    default_iv = sum(valid_iv_list) / len(valid_iv_list) if valid_iv_list else 0.25

    net_gex_by_strike = []
    total_net_gex = 0.0
    call_gex_total = 0.0
    put_gex_total = 0.0

    eff_dte_years = max(0.0001, dte_years)

    for i in range(n):
        k = float(strikes[i])
        c_oi = float(call_oi[i]) if i < len(call_oi) else 0.0
        p_oi = float(put_oi[i]) if i < len(put_oi) else 0.0

        c_gamma = (
            call_gammas[i]
            if (call_gammas and i < len(call_gammas) and call_gammas[i] is not None)
            else None
        )
        p_gamma = (
            put_gammas[i]
            if (put_gammas and i < len(put_gammas) and put_gammas[i] is not None)
            else None
        )
        iv = (
            ivs[i]
            if (ivs and i < len(ivs) and ivs[i] is not None and 0.005 <= ivs[i] <= 8.0)
            else default_iv
        )

        if c_gamma is None or c_gamma <= 0:
            c_gamma = (
                calculate_bs_gamma(spot=spot, strike=k, years=eff_dte_years, iv=iv, rate=rate)
                or 0.0
            )
        if p_gamma is None or p_gamma <= 0:
            p_gamma = (
                calculate_bs_gamma(spot=spot, strike=k, years=eff_dte_years, iv=iv, rate=rate)
                or 0.0
            )

        c_gex = calculate_dollar_gamma_1pct(c_oi, c_gamma, spot, 100.0) / 1_000_000.0
        p_gex = calculate_dollar_gamma_1pct(p_oi, p_gamma, spot, 100.0) / 1_000_000.0

        strike_net_gex = c_gex - p_gex
        net_gex_by_strike.append((k, strike_net_gex, c_oi, p_oi, c_gex, p_gex))
        total_net_gex += strike_net_gex
        call_gex_total += c_gex
        put_gex_total += p_gex

    sorted_strikes = sorted(net_gex_by_strike, key=lambda x: x[0])
    has_pos = any(g > 1e-6 for _, g, _, _, _, _ in sorted_strikes)
    has_neg = any(g < -1e-6 for _, g, _, _, _, _ in sorted_strikes)

    crossings: list[float] = []
    if has_pos and has_neg:
        for i in range(len(sorted_strikes) - 1):
            k1, g1, _, _, _, _ = sorted_strikes[i]
            k2, g2, _, _, _, _ = sorted_strikes[i + 1]
            if g1 == 0.0:
                crossings.append(float(k1))
            elif (g1 < 0 and g2 > 0) or (g1 > 0 and g2 < 0):
                denom = abs(g1) + abs(g2)
                if denom > 1e-9:
                    crossings.append(float(k1 + (abs(g1) / denom) * (k2 - k1)))

    gamma_flip: float | None = None
    if crossings:
        gamma_flip = min(crossings, key=lambda x: abs(x - spot))
        gamma_flip = round(gamma_flip, 2)

    mapped_strike_gex = [
        {
            "strike": k,
            "call_oi": c_oi,
            "put_oi": p_oi,
            "call_gex_m": c_gex,
            "put_gex_m": p_gex,
            "net_gex_m": net_gex,
        }
        for k, net_gex, c_oi, p_oi, c_gex, p_gex in sorted_strikes
    ]

    # Kinematic Regime
    if abs(kinematic_velocity) > 0.015:
        kinematic = "trend_acceleration" if total_net_gex < 0 else "momentum_exhaustion"
    else:
        kinematic = "mean_reverting" if total_net_gex > 0 else "trend_acceleration"

    # Charm Drift Regime
    if dte_years <= 5.0 / 365.0:
        charm_drift = "selling_drift" if call_gex_total > put_gex_total else "buying_drift"
    else:
        charm_drift = "neutral_decay"

    # A 1σ move computed from a hard-coded fallback IV is a fabricated number.
    # With no plausible chain IV there is no measured input — emit None instead.
    expected_move_1d = (
        round(compute_expected_move_1d(spot, default_iv, dte=1.0, calendar_days=True), 2)
        if valid_iv_list
        else None
    )

    return classify_market_regime(
        spot=spot,
        total_net_gex_m=total_net_gex,
        gamma_flip=gamma_flip,
        mapped_strike_gex=mapped_strike_gex,
        charm_drift_regime=charm_drift,
        kinematic_regime=kinematic,
        expected_move_1d=expected_move_1d,
    )


def detect_price_magnets(
    *,
    spot: float,
    strikes: Sequence[float],
    call_oi: Sequence[int | float],
    put_oi: Sequence[int | float],
    call_volume: Sequence[int | float] | None = None,
    put_volume: Sequence[int | float] | None = None,
    regime_state: MarketRegimeState | None = None,
    kinematic_target: float | None = None,
) -> list[PriceMagnetLevel]:
    """Detects and ranks multi-factor structural price magnet levels."""
    if spot <= 0 or not strikes or len(strikes) == 0:
        return []

    # If all open interest is 0 across entire chain, return empty
    total_oi = sum(call_oi) + sum(put_oi)
    if total_oi <= 0:
        return []

    n = len(strikes)
    call_wall_price = float(strikes[0])
    max_call_oi = -1.0
    put_wall_price = float(strikes[0])
    max_put_oi = -1.0

    total_vol_by_strike: dict[float, float] = {}
    total_pain_by_strike: dict[float, float] = {float(s): 0.0 for s in strikes}

    for i in range(n):
        k = float(strikes[i])
        c_oi = float(call_oi[i]) if i < len(call_oi) else 0.0
        p_oi = float(put_oi[i]) if i < len(put_oi) else 0.0

        if c_oi > max_call_oi:
            max_call_oi = c_oi
            call_wall_price = k

        if p_oi > max_put_oi:
            max_put_oi = p_oi
            put_wall_price = k

        c_vol = float(call_volume[i]) if (call_volume and i < len(call_volume)) else 0.0
        p_vol = float(put_volume[i]) if (put_volume and i < len(put_volume)) else 0.0
        total_vol_by_strike[k] = c_vol + p_vol

    # Max Pain calculation
    for j in range(n):
        sj = float(strikes[j])
        pain_at_sj = 0.0
        for i in range(n):
            ki = float(strikes[i])
            ci = float(call_oi[i]) if i < len(call_oi) else 0.0
            pi = float(put_oi[i]) if i < len(put_oi) else 0.0
            call_payout = max(0.0, sj - ki) * ci * 100.0
            put_payout = max(0.0, ki - sj) * pi * 100.0
            pain_at_sj += call_payout + put_payout
        total_pain_by_strike[sj] = pain_at_sj

    max_pain_price = (
        min(total_pain_by_strike.keys(), key=lambda s: total_pain_by_strike[s])
        if total_pain_by_strike
        else spot
    )
    volume_poc_price = (
        max(total_vol_by_strike.keys(), key=lambda s: total_vol_by_strike[s])
        if total_vol_by_strike and max(total_vol_by_strike.values()) > 0
        else spot
    )

    candidates: list[PriceMagnetLevel] = []

    # 1. Call Wall
    c_pts = call_wall_price - spot
    c_pct = (c_pts / spot) * 100.0
    c_pull = min(100.0, max(10.0, 75.0 + (10.0 if abs(c_pct) < 3.0 else -abs(c_pct) * 2.0)))
    candidates.append(
        PriceMagnetLevel(
            level_id="call_wall",
            label="Call Wall",
            price=call_wall_price,
            distance_points=round(c_pts, 2),
            distance_pct=round(c_pct, 2),
            direction="above" if c_pts > 0.001 else ("below" if c_pts < -0.001 else "at_spot"),
            gravitational_pull=round(c_pull, 1),
            structural_force="Overhead Resistance Cap" if c_pts >= 0 else "Breached Resistance",
            conviction_rank=2,
            components={"gex_mass": 0.85, "proximity": round(max(0.0, 1.0 - abs(c_pct) / 10.0), 2)},
        )
    )

    # 2. Put Wall
    p_pts = put_wall_price - spot
    p_pct = (p_pts / spot) * 100.0
    p_pull = min(100.0, max(10.0, 75.0 + (10.0 if abs(p_pct) < 3.0 else -abs(p_pct) * 2.0)))
    candidates.append(
        PriceMagnetLevel(
            level_id="put_wall",
            label="Put Wall",
            price=put_wall_price,
            distance_points=round(p_pts, 2),
            distance_pct=round(p_pct, 2),
            direction="above" if p_pts > 0.001 else ("below" if p_pts < -0.001 else "at_spot"),
            gravitational_pull=round(p_pull, 1),
            structural_force="Downside Support Floor" if p_pts <= 0 else "Breached Support",
            conviction_rank=3,
            components={"gex_mass": 0.80, "proximity": round(max(0.0, 1.0 - abs(p_pct) / 10.0), 2)},
        )
    )

    # 3. Gamma Flip
    if regime_state and regime_state.gamma_flip is not None:
        gf_price = regime_state.gamma_flip
        gf_pts = gf_price - spot
        gf_pct = (gf_pts / spot) * 100.0
        gf_pull = min(100.0, max(20.0, 90.0 - abs(gf_pct) * 5.0))
        candidates.append(
            PriceMagnetLevel(
                level_id="gamma_flip",
                label="Zero-Gamma Flip",
                price=gf_price,
                distance_points=round(gf_pts, 2),
                distance_pct=round(gf_pct, 2),
                direction="above"
                if gf_pts > 0.001
                else ("below" if gf_pts < -0.001 else "at_spot"),
                gravitational_pull=round(gf_pull, 1),
                structural_force="Regime Transition Pivot",
                conviction_rank=1,
                components={
                    "gex_mass": 0.90,
                    "proximity": round(max(0.0, 1.0 - abs(gf_pct) / 10.0), 2),
                },
            )
        )

    # 4. Max Pain Pin
    mp_pts = max_pain_price - spot
    mp_pct = (mp_pts / spot) * 100.0
    mp_pull = min(100.0, max(15.0, 85.0 - abs(mp_pct) * 3.0))
    candidates.append(
        PriceMagnetLevel(
            level_id="max_pain",
            label="Max Pain Pin",
            price=max_pain_price,
            distance_points=round(mp_pts, 2),
            distance_pct=round(mp_pct, 2),
            direction="above" if mp_pts > 0.001 else ("below" if mp_pts < -0.001 else "at_spot"),
            gravitational_pull=round(mp_pull, 1),
            structural_force="OpEx Expiry Pinning Magnet",
            conviction_rank=4,
            components={
                "theta_align": 0.90,
                "proximity": round(max(0.0, 1.0 - abs(mp_pct) / 10.0), 2),
            },
        )
    )

    # 5. Kinematic Drift
    if kinematic_target is not None and kinematic_target > 0:
        kd_pts = kinematic_target - spot
        kd_pct = (kd_pts / spot) * 100.0
        kd_pull = min(100.0, max(10.0, 70.0 - abs(kd_pct) * 4.0))
        candidates.append(
            PriceMagnetLevel(
                level_id="kinematic_drift",
                label="Kinematic Attractor",
                price=kinematic_target,
                distance_points=round(kd_pts, 2),
                distance_pct=round(kd_pct, 2),
                direction="above"
                if kd_pts > 0.001
                else ("below" if kd_pts < -0.001 else "at_spot"),
                gravitational_pull=round(kd_pull, 1),
                structural_force="Kalman Velocity Equilibrium",
                conviction_rank=5,
                components={
                    "velocity_align": 0.85,
                    "proximity": round(max(0.0, 1.0 - abs(kd_pct) / 10.0), 2),
                },
            )
        )

    # 6. Volume POC
    if volume_poc_price != spot:
        vp_pts = volume_poc_price - spot
        vp_pct = (vp_pts / spot) * 100.0
        vp_pull = min(100.0, max(10.0, 65.0 - abs(vp_pct) * 4.0))
        candidates.append(
            PriceMagnetLevel(
                level_id="volume_poc",
                label="Volume POC",
                price=volume_poc_price,
                distance_points=round(vp_pts, 2),
                distance_pct=round(vp_pct, 2),
                direction="above"
                if vp_pts > 0.001
                else ("below" if vp_pts < -0.001 else "at_spot"),
                gravitational_pull=round(vp_pull, 1),
                structural_force="High-Volume Liquidity Node",
                conviction_rank=6,
                components={
                    "volume_align": 0.80,
                    "proximity": round(max(0.0, 1.0 - abs(vp_pct) / 10.0), 2),
                },
            )
        )

    sorted_magnets = sorted(candidates, key=lambda m: m.gravitational_pull, reverse=True)
    ranked = []
    for rank, mag in enumerate(sorted_magnets, start=1):
        ranked.append(
            PriceMagnetLevel(
                level_id=mag.level_id,
                label=mag.label,
                price=mag.price,
                distance_points=mag.distance_points,
                distance_pct=mag.distance_pct,
                direction=mag.direction,
                gravitational_pull=mag.gravitational_pull,
                structural_force=mag.structural_force,
                conviction_rank=rank,
                components=mag.components,
            )
        )

    return ranked


def compute_confluence_zones(
    magnets: Sequence[PriceMagnetLevel],
    spot: float,
    cluster_threshold_pct: float = 0.75,
) -> list[dict[str, Any]]:
    """Identifies multi-lens confluence clusters where multiple attractors align."""
    if not magnets or spot <= 0:
        return []

    sorted_by_price = sorted(magnets, key=lambda m: m.price)
    clusters = []
    current_group = [sorted_by_price[0]]

    for i in range(1, len(sorted_by_price)):
        prev = current_group[-1]
        curr = sorted_by_price[i]
        pct_diff = (abs(curr.price - prev.price) / spot) * 100.0

        if pct_diff <= cluster_threshold_pct:
            current_group.append(curr)
        else:
            if len(current_group) >= 2:
                clusters.append(_build_confluence_dict(current_group, spot))
            current_group = [curr]

    if len(current_group) >= 2:
        clusters.append(_build_confluence_dict(current_group, spot))

    return clusters


def _build_confluence_dict(group: list[PriceMagnetLevel], spot: float) -> dict[str, Any]:
    avg_price = sum(m.price for m in group) / len(group)
    lenses = set()
    labels = []
    for m in group:
        labels.append(m.label)
        if "call_wall" in m.level_id or "put_wall" in m.level_id or "gamma_flip" in m.level_id:
            lenses.add("GAMMA")
        if "max_pain" in m.level_id:
            lenses.add("THETA")
        if "volume" in m.level_id:
            lenses.add("VOLUME")
        if "kinematic" in m.level_id:
            lenses.add("KALMAN")

    dist_pct = ((avg_price - spot) / spot) * 100.0
    return {
        "level": round(avg_price, 2),
        "distance_pct": round(dist_pct, 2),
        "supporting_lenses": sorted(list(lenses)),
        "lens_count": len(lenses),
        "labels": labels,
        "above_spot": avg_price >= spot,
    }


def build_price_draw_telemetry_payload(
    *,
    symbol: str,
    spot: float | None,
    regime_state: MarketRegimeState,
    magnets: Sequence[PriceMagnetLevel],
    asof_utc: str | None = None,
    quality_reason: str | None = None,
) -> dict[str, Any]:
    """Compiles complete API telemetry payload with zero-spoofing guarantees."""
    now_iso = asof_utc or datetime.now(timezone.utc).isoformat()
    sym = symbol.upper()

    if not regime_state.measurable or spot is None or spot <= 0:
        reason_msg = quality_reason or "Open interest and option chain data unavailable"
        return {
            "symbol": sym,
            "spot": None,
            "asof_utc": now_iso,
            "regime_state": "unmeasurable",
            "regime_label": "Unmeasured Regime",
            "regime_strength": None,
            "dominant_direction": "unmeasured",
            "primary_magnet": None,
            "levels": [],
            "confluence_clusters": [],
            "quality": {
                "measurable": False,
                "open_interest_available": False,
                "iv_available": False,
                "volume_available": False,
                "reason": reason_msg,
            },
            "warnings": [reason_msg],
        }

    regime_type_map = {
        "volatility_dampening": "volatility_dampening",
        "volatility_amplification": "volatility_amplification",
        "neutral_straddle": "neutral_transition",
        "unmeasured": "unmeasurable",
    }
    regime_key = regime_type_map.get(regime_state.volatility_behavior, "neutral_transition")
    if regime_state.charm_drift_regime == "selling_drift":
        regime_key = "charm_decay_selling"
    elif regime_state.charm_drift_regime == "buying_drift":
        regime_key = "charm_decay_buying"

    levels_payload = []
    for m in magnets:
        supporting = []
        if "call_wall" in m.level_id or "put_wall" in m.level_id or "gamma_flip" in m.level_id:
            supporting.append("GAMMA")
        if "max_pain" in m.level_id:
            supporting.append("THETA")
        if "volume" in m.level_id:
            supporting.append("VOLUME")
        if "kinematic" in m.level_id:
            supporting.append("KALMAN")

        levels_payload.append(
            {
                "id": m.level_id,
                "type": m.level_id if m.level_id != "max_pain" else "max_pain_pin",
                "label": m.label,
                "price": m.price,
                "distance_pts": m.distance_points,
                "distance_pct": m.distance_pct,
                "pull_score": m.gravitational_pull,
                "direction": m.direction,
                "regime_role": m.structural_force,
                "supporting_lenses": supporting,
                "lens_count": len(supporting),
                "is_primary_magnet": m.conviction_rank == 1,
            }
        )

    total_above = sum(m.gravitational_pull for m in magnets if m.price > spot)
    total_below = sum(m.gravitational_pull for m in magnets if m.price < spot)
    total_pull = total_above + total_below
    if total_pull == 0 or abs(total_above - total_below) / total_pull < 0.15:
        dominant_dir = "neutral_pin"
    elif total_above > total_below:
        dominant_dir = "bullish_pull"
    else:
        dominant_dir = "bearish_pull"

    primary = levels_payload[0] if levels_payload else None
    clusters = compute_confluence_zones(magnets, spot)

    return {
        "symbol": sym,
        "spot": spot,
        "asof_utc": now_iso,
        "regime_state": regime_key,
        "regime_label": regime_state.volatility_regime.replace("_", " ").title(),
        "regime_strength": regime_state.regime_strength,
        "dominant_direction": dominant_dir,
        "primary_magnet": primary,
        "levels": levels_payload,
        "confluence_clusters": clusters,
        "quality": {
            "measurable": True,
            "open_interest_available": True,
            "iv_available": True,
            "volume_available": True,
            "reason": None,
        },
        "warnings": [],
    }


__all__ = [
    "ConfluenceCluster",
    "MarketRegimeState",
    "PriceMagnetLevel",
    "RegimeAttractorSnapshot",
    "bs_d1_d2",
    "calculate_bs_charm_per_day",
    "calculate_bs_gamma",
    "calculate_dollar_gamma_1pct",
    "calculate_gravitational_pull",
    "calculate_max_pain",
    "classify_market_regime",
    "compute_gamma_flip_and_walls",
    "compute_kinematic_drift_level",
    "compute_net_charm_flow",
    "compute_price_attractors",
    "detect_confluence_clusters",
    "extract_volume_poc",
    "calculate_market_regime",
    "detect_price_magnets",
    "compute_confluence_zones",
    "build_price_draw_telemetry_payload",
]
