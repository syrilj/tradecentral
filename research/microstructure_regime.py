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
#: Half-width of the neutral band around the flip, as a fraction of spot.
#: Matches DEFAULT_FLIP_BAND_PCT in dashboard/src/gammaRegime.ts -- the two
#: ends must agree on where "straddling the flip" starts or the same tape
#: reads as neutral on one panel and directional on another.
_FLIP_BAND_PCT = 0.0025
#: A net GEX reading smaller than this fraction of the symbol's own peak
#: |net GEX| is noise, not a posture. Relative for the same reason
#: _regime_strength is: an absolute $M floor cannot serve both SPY and a
#: single name.
_NEUTRAL_GEX_FRACTION = 0.05


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
    put_gex_m: float  # $ Millions per 1% spot move
    net_gex_m: float  # Net Dealer GEX ($M)
    call_vex_m: float  # Vanna exposure ($M per 1% IV shift)
    put_vex_m: float
    net_vex_m: float
    call_chex_m: float  # Charm exposure ($M per day)
    put_chex_m: float
    net_chex_m: float
    speed_m: float  # Speed ($M per 1% spot move / $ spot)
    zomma_m: float  # Zomma ($M per 1% spot move / 1% IV)


@dataclass(frozen=True)
class TopographyState:
    """Topographical classification of dealer gamma surface.

    `quadrant` is "unmeasurable" whenever the flip level could not be located
    (see `_nearest_flip`): the four named quadrants are all defined relative to
    S*, so without it there is no quadrant to name and inventing one would put a
    confident label on a read that does not exist.
    """

    quadrant: str  # "forward_positive_ramp" | "backward_positive_ramp" | "forward_negative_slide" | "backward_negative_slide" | "unmeasurable"
    title: str
    description: str
    dealer_hedging_action: str
    expected_market_behavior: str
    gex_above_spot_m: float
    gex_below_spot_m: float
    gex_ratio: float
    call_wall: float | None
    put_wall: float | None
    gamma_flip: float | None
    volatility_trigger: float | None
    absolute_gamma_peak: float | None


@dataclass(frozen=True)
class ChainQuality:
    """What the snapshot below was actually measured from.

    Every downstream consumer needs this to decide whether it may render a
    directional claim. A regime read carries no meaning without knowing that
    real open interest stood behind it, so the numbers and the evidence for
    them travel together rather than the UI having to infer trustworthiness
    from a plausible-looking value.
    """

    measurable: bool
    contracts: int
    strikes: int
    total_open_interest: int
    iv_fallback_contracts: int  # contracts priced off the default IV, not a quote
    flip_located: bool
    dealer_convention: str  # "index" | "equity" -- which sign assumption produced these numbers
    reason: str | None = None  # why measurable is False


@dataclass(frozen=True)
class SharedLevels:
    """Structural levels measured elsewhere, to be adopted verbatim.

    The dashboard's /regime page draws on two producers of dealer-gamma
    numbers: this module (which also carries vanna, charm, speed and zomma)
    and `daily_plays.options_intelligence._gex_map` (which the front end reads
    directly as `gex_price_profile`). When each derived its own flip, walls and
    net GEX from its own grid, the same screen showed two different answers to
    the same question and the operator had no way to tell which one to believe.

    Passing this in makes `_gex_map` the single authority for the levels both
    consumers share, so the classification here is derived from exactly the
    numbers the UI renders rather than from a parallel measurement of them.
    The Greeks this module adds on top are still computed here -- nothing else
    produces them.
    """

    gex_profile: Sequence[Mapping[str, float]]  # spot -> net_gex_m, the authoritative curve
    call_wall: float | None
    put_wall: float | None
    gamma_flip: float | None = None
    pin_strike: float | None = None


@dataclass(frozen=True)
class MicrostructureRegimeSnapshot:
    """Unified snapshot of microstructure regime dynamics."""

    symbol: str
    spot: float
    asof: str
    regime: str  # "positive_gamma" | "negative_gamma" | "neutral_transition" | "unmeasurable"
    #: Scale-free strength of the regime call in [0, 1] -- NOT a probability.
    #: See `_regime_strength` for the definition; it is the smaller of "how
    #: large is net GEX against this symbol's own range" and "how far is spot
    #: from the flip", so a big number requires both to agree.
    regime_strength: float
    #: Per-strike sum at spot. `call_gex_m + put_gex_m` equals this exactly.
    net_gex_m: float
    call_gex_m: float
    put_gex_m: float
    #: The same quantity read off `gex_profile` at spot -- the curve the flip and
    #: the gamma map are drawn from, and what the front end interpolates live
    #: between chain refreshes. Reported alongside `net_gex_m` rather than
    #: replacing it; see the note at its assignment.
    net_gex_profile_m: float | None
    net_vex_m: float
    net_chex_m: float
    #: None when the spot/IV velocities it needs were not measured -- this is
    #: an instantaneous flow *rate*, and a rate computed from an assumed
    #: velocity is an assumption wearing a number's clothes.
    hedging_flow_m: float | None
    zero_dte_charm_drift_m: float  # Expected 0DTE afternoon charm drift ($M)
    gamma_flip: float | None
    call_wall: float | None
    put_wall: float | None
    volatility_trigger: float | None
    absolute_gamma_peak: float | None
    quality: ChainQuality
    topography: TopographyState
    strikes: list[StrikeExposure]
    gex_profile: list[dict[str, float]]  # Net dealer GEX ($M) evaluated across spot
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
    return open_interest * multiplier * gamma * (spot**2) * 0.01


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


def unmeasurable_regime_snapshot(
    *,
    symbol: str,
    spot: float,
    asof: str,
    dealer_convention: str,
    contracts: int,
    strikes: int,
    total_open_interest: int,
    reason: str,
) -> "MicrostructureRegimeSnapshot":
    """The snapshot for "we could not measure this".

    Every numeric level is None and every classification string says so. The
    alternative -- zeros and a neutral-sounding quadrant -- is indistinguishable
    on screen from a genuine balanced read, which is the single most expensive
    confusion this module can cause.
    """
    return MicrostructureRegimeSnapshot(
        symbol=symbol,
        spot=round(spot, 2),
        asof=asof,
        regime="unmeasurable",
        regime_strength=0.0,
        net_gex_m=0.0,
        call_gex_m=0.0,
        put_gex_m=0.0,
        net_gex_profile_m=None,
        net_vex_m=0.0,
        net_chex_m=0.0,
        hedging_flow_m=None,
        zero_dte_charm_drift_m=0.0,
        gamma_flip=None,
        call_wall=None,
        put_wall=None,
        volatility_trigger=None,
        absolute_gamma_peak=None,
        quality=ChainQuality(
            measurable=False,
            contracts=contracts,
            strikes=strikes,
            total_open_interest=total_open_interest,
            iv_fallback_contracts=0,
            flip_located=False,
            dealer_convention=dealer_convention,
            reason=reason,
        ),
        topography=TopographyState(
            quadrant="unmeasurable",
            title="Not measurable",
            description=f"No dealer gamma surface could be measured: {reason}.",
            dealer_hedging_action="Unknown -- no position data to infer hedging from.",
            expected_market_behavior="No claim. This surface contributes nothing to a decision right now.",
            gex_above_spot_m=0.0,
            gex_below_spot_m=0.0,
            gex_ratio=0.0,
            call_wall=None,
            put_wall=None,
            gamma_flip=None,
            volatility_trigger=None,
            absolute_gamma_peak=None,
        ),
        strikes=[],
        gex_profile=[],
        notes=[f"Regime withheld: {reason}."],
    )


# ---------------------------------------------------------------------------
# Level selection
#
# These three helpers exist because the naive formulations they replace all
# produced levels that were wrong in the same direction: confidently placed,
# and unfalsifiable from the UI. Each one now either returns a level the
# profile actually supports, or None.
# ---------------------------------------------------------------------------


def _build_gex_profile(
    *,
    strike_map: Mapping[float, Mapping[str, Any]],
    sorted_strikes: Sequence[float],
    spot: float,
    rate: float,
    phi_call: float,
    phi_put: float,
) -> list[dict[str, float]]:
    """Net dealer GEX ($M) revalued across a grid of hypothetical spots.

    This is the gamma map: at each test spot every contract's gamma is
    recomputed and summed, so the curve shows what dealer inventory would look
    like if price moved there. The zero crossing of this curve is the flip.
    """
    min_strike = sorted_strikes[0] if sorted_strikes else spot * 0.8
    max_strike = sorted_strikes[-1] if sorted_strikes else spot * 1.2
    test_spots = np.linspace(min_strike * 0.95, max_strike * 1.05, 50)
    profile: list[dict[str, float]] = []
    for s_test in test_spots:
        s_gex = 0.0
        for k in sorted_strikes:
            entry = strike_map[k]
            call_iv = entry["call_iv"] or 0.20
            put_iv = entry["put_iv"] or 0.20
            call_years = entry["call_years"] or (30.0 / 365.25)
            put_years = entry["put_years"] or (30.0 / 365.25)

            cg_test = calculate_option_greeks(
                spot=float(s_test), strike=k, years=call_years, iv=call_iv, right="call", rate=rate
            )
            pg_test = calculate_option_greeks(
                spot=float(s_test), strike=k, years=put_years, iv=put_iv, right="put", rate=rate
            )
            c_gamma = cg_test.gamma if cg_test else 0.0
            p_gamma = pg_test.gamma if pg_test else 0.0

            c_gex = calculate_contract_gex(
                open_interest=entry["call_oi"], gamma=c_gamma, spot=float(s_test)
            )
            p_gex = calculate_contract_gex(
                open_interest=entry["put_oi"], gamma=p_gamma, spot=float(s_test)
            )
            s_gex += (phi_call * c_gex + phi_put * p_gex) / 1e6

        profile.append({"spot": round(float(s_test), 2), "net_gex_m": round(s_gex, 4)})
    return profile


def _interpolate_profile(profile: Sequence[Mapping[str, float]], spot: float) -> float:
    """Net GEX at `spot`, linearly interpolated, clamped at the profile edges.

    Deliberately mirrors `interpolateNetGamma` in dashboard/src/gammaRegime.ts,
    including the clamp: past the last measured strike the shape was never
    observed, so extrapolating it would invent gamma that no open interest
    supports.
    """
    pts = sorted(profile, key=lambda pt: float(pt["spot"]))
    if not pts:
        return 0.0
    if len(pts) == 1 or spot <= float(pts[0]["spot"]):
        return float(pts[0]["net_gex_m"])
    if spot >= float(pts[-1]["spot"]):
        return float(pts[-1]["net_gex_m"])
    for a, b in zip(pts, pts[1:]):
        x0, x1 = float(a["spot"]), float(b["spot"])
        if x0 <= spot <= x1:
            if x1 == x0:
                return float(a["net_gex_m"])
            t = (spot - x0) / (x1 - x0)
            return float(a["net_gex_m"]) + t * (float(b["net_gex_m"]) - float(a["net_gex_m"]))
    return float(pts[-1]["net_gex_m"])


def _nearest_flip(profile: Sequence[Mapping[str, float]], spot: float) -> float | None:
    """Zero-gamma level: the sign change in net GEX *closest to spot*.

    Scanning the profile bottom-up and taking the first crossing is wrong
    whenever the curve crosses more than once (routine on a chain with heavy
    OI both above and below spot): it returns whichever root happens to sit
    lowest in the tested spot range, which can be 15% away and on the far side
    of the market. Everything downstream then compares spot against a boundary
    from a different part of the surface and concludes the opposite regime.

    Returns None when the profile never changes sign. That case is real and
    common -- a chain that is positive-gamma across every tested spot has no
    flip -- and the honest answer is "there isn't one", not a placeholder at
    spot * 0.95 that reads on screen exactly like a measured level.
    """
    crossings: list[float] = []
    for a, b in zip(profile, profile[1:]):
        y0, y1 = float(a["net_gex_m"]), float(b["net_gex_m"])
        if y0 == 0.0:
            crossings.append(float(a["spot"]))
        elif y0 * y1 < 0:
            x0, x1 = float(a["spot"]), float(b["spot"])
            crossings.append(x0 + (x1 - x0) * abs(y0) / (abs(y0) + abs(y1)))
    if not crossings:
        return None
    return min(crossings, key=lambda x: abs(x - spot))


def _directional_walls(
    exposures: Sequence["StrikeExposure"],
    spot: float,
) -> tuple[float | None, float | None]:
    """Call wall above spot, put wall below spot.

    A global argmax over |call_gex_m| and |put_gex_m| ignores which side of
    spot the strike sits on, and since both gamma concentrations peak near the
    money it lands *both* walls on the same ATM strike -- so the UI draws
    "resistance" and "support" as one line and the pivot ladder degenerates.
    A wall is defined by its side: resistance is the heaviest call gamma
    *above* the market, support the heaviest put gamma *below* it.

    Magnitude rather than the signed value keeps this independent of the
    dealer sign convention -- a wall is where gamma is concentrated, which is
    a fact about open interest, not about who is assumed to be short it.
    """
    above = [e for e in exposures if e.strike > spot]
    below = [e for e in exposures if e.strike < spot]
    call_wall = max(above, key=lambda e: abs(e.call_gex_m)).strike if above else None
    put_wall = max(below, key=lambda e: abs(e.put_gex_m)).strike if below else None
    return call_wall, put_wall


def _regime_strength(net_gex_m: float, gex_scale_m: float, distance_to_flip: float | None) -> float:
    """How firmly the regime call is established, in [0, 1]. Not a probability.

    The formulation this replaces was `0.70 + net_gex / 500`, which is an
    absolute $M constant: SPY's net gamma runs three orders of magnitude above
    a single name's, so it pinned to the 0.98 ceiling on every index read and
    never left the floor on a single name. The same defect was already found
    and fixed on the front end (see gammaTilt's GAMMA_NORMALIZATION_M note) --
    this is the server-side twin of it.

    Scale-free instead: normalize net GEX against this symbol's own observed
    range, and take the *minimum* of that and the normalized distance to the
    flip. Minimum, not average, because the two must agree -- a huge net GEX
    reading while spot sits on the flip is precisely the situation where the
    regime is about to change hands, and averaging would hide that behind the
    large term.
    """
    if gex_scale_m <= 0:
        return 0.0
    magnitude = math.tanh(abs(net_gex_m) / gex_scale_m)
    if distance_to_flip is None:
        # No flip located: magnitude is the only evidence, and it is weaker
        # evidence on its own, so it does not get to claim the whole range.
        return round(min(1.0, magnitude * 0.6), 3)
    proximity = math.tanh(abs(distance_to_flip) / _FLIP_BAND_PCT)
    return round(min(magnitude, proximity), 3)


def compute_microstructure_regime(
    chain_rows: Sequence[Mapping[str, Any]],
    *,
    symbol: str = "SPY",
    spot: float,
    rate: float = _DEFAULT_RATE,
    asof: str = "",
    is_index: bool = True,
    ds_dt_pct: float | None = None,  # Daily spot return rate (e.g. +0.01 = +1%)
    dvol_dt_pct: float | None = None,  # Daily IV change rate (e.g. -0.02 = -2% IV)
    shared_levels: SharedLevels | None = None,
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
        ds_dt_pct: Measured spot velocity (0.01 = +1% on the day). None when it
            was not measured -- `hedging_flow_m` is then withheld rather than
            computed from an assumed velocity.
        dvol_dt_pct: Measured IV velocity, same convention and same treatment.
        shared_levels: Authoritative profile and walls measured upstream. When
            supplied they replace this module's own grid so that every consumer
            of the same chain reports the same levels -- see SharedLevels.

    Returns:
        MicrostructureRegimeSnapshot with complete Greeks, topography, and structural levels.
        Every structural level is nullable and `quality` states what the numbers
        were measured from; callers must not render a directional claim when
        `quality.measurable` is False.
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
    dealer_convention = "index" if is_index else "equity"

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
            right_norm = (
                "call"
                if right in {"c", "call", "calls"}
                else "put"
                if right in {"p", "put", "puts"}
                else None
            )
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

    total_oi = sum(int(e["call_oi"]) + int(e["put_oi"]) for e in strike_map.values())
    if not strike_map or total_oi <= 0:
        # No open interest means there is no dealer inventory to have a gamma
        # posture about. Returning a zeroed snapshot here would render on screen
        # as a real neutral read; withholding is the only honest answer.
        return unmeasurable_regime_snapshot(
            symbol=symbol,
            spot=spot,
            asof=asof,
            dealer_convention=dealer_convention,
            contracts=len(chain_rows),
            strikes=len(strike_map),
            total_open_interest=total_oi,
            reason="no open interest in the supplied chain",
        )

    # Compute Greeks and exposures per strike
    iv_fallback_contracts = 0
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
        if entry["call_iv"] is None and entry["call_oi"] > 0:
            iv_fallback_contracts += 1
        if entry["put_iv"] is None and entry["put_oi"] > 0:
            iv_fallback_contracts += 1
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
        call_gex_raw = calculate_contract_gex(
            open_interest=entry["call_oi"], gamma=call_gamma, spot=spot
        )
        put_gex_raw = calculate_contract_gex(
            open_interest=entry["put_oi"], gamma=put_gamma, spot=spot
        )
        call_gex_m = (phi_call * call_gex_raw) / 1e6
        put_gex_m = (phi_put * put_gex_raw) / 1e6
        net_gex_m = call_gex_m + put_gex_m

        # Vanna ($M)
        call_vanna = cg.vanna if cg else 0.0
        put_vanna = pg.vanna if pg else 0.0
        call_vex_raw = calculate_contract_vex(
            open_interest=entry["call_oi"], vanna=call_vanna, spot=spot
        )
        put_vex_raw = calculate_contract_vex(
            open_interest=entry["put_oi"], vanna=put_vanna, spot=spot
        )
        call_vex_m = (phi_call * call_vex_raw) / 1e6
        put_vex_m = (phi_put * put_vex_raw) / 1e6
        net_vex_m = call_vex_m + put_vex_m

        # Charm ($M per day)
        call_charm = cg.charm if cg else 0.0
        put_charm = pg.charm if pg else 0.0
        call_chex_raw = calculate_contract_chex(
            open_interest=entry["call_oi"], charm=call_charm, spot=spot
        )
        put_chex_raw = calculate_contract_chex(
            open_interest=entry["put_oi"], charm=put_charm, spot=spot
        )
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
        speed_raw = (
            (entry["call_oi"] * call_speed + entry["put_oi"] * put_speed) * 100.0 * (spot**2) * 0.01
        )
        speed_m = speed_raw / 1e6

        call_zomma = cg.zomma if cg else 0.0
        put_zomma = pg.zomma if pg else 0.0
        zomma_raw = (
            (entry["call_oi"] * call_zomma + entry["put_oi"] * put_zomma) * 100.0 * (spot**2) * 0.01
        )
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

    # Compute Structural Boundaries. Walls are directional (see
    # _directional_walls); the two peak levels are genuinely global, so they
    # stay argmax -- but they are None on an empty ladder rather than spot.
    if strike_exposures:
        call_wall, put_wall = _directional_walls(strike_exposures, spot)
        volatility_trigger = max(
            strike_exposures, key=lambda s: abs(s.speed_m) + abs(s.zomma_m)
        ).strike
        absolute_gamma_peak = max(strike_exposures, key=lambda s: abs(s.net_gex_m)).strike
    else:
        call_wall = put_wall = volatility_trigger = absolute_gamma_peak = None
    if shared_levels is not None:
        # Upstream measured these from the same chain and the UI already renders
        # them; adopting rather than re-deriving is what keeps the page from
        # contradicting itself.
        if shared_levels.call_wall is not None:
            call_wall = shared_levels.call_wall
        if shared_levels.put_wall is not None:
            put_wall = shared_levels.put_wall
        if shared_levels.pin_strike is not None:
            absolute_gamma_peak = shared_levels.pin_strike

    # Net dealer GEX ($M) evaluated across spot -- the curve the flip is read
    # off. Recomputed here only when upstream did not already supply it.
    if shared_levels is not None and len(shared_levels.gex_profile) >= 2:
        gex_profile: list[dict[str, float]] = [
            {"spot": float(pt["spot"]), "net_gex_m": float(pt["net_gex_m"])}
            for pt in shared_levels.gex_profile
        ]
    else:
        gex_profile = _build_gex_profile(
            strike_map=strike_map,
            sorted_strikes=sorted_strikes,
            spot=spot,
            rate=rate,
            phi_call=phi_call,
            phi_put=phi_put,
        )

    # Find Gamma Flip S* (root where Net GEX = 0), nearest spot. None when the
    # profile never changes sign -- there is no flip to report, and the old
    # spot * 0.95 / spot * 1.05 placeholders were indistinguishable from a
    # measured level once they reached the UI.
    if shared_levels is not None and shared_levels.gamma_flip is not None:
        gamma_flip = shared_levels.gamma_flip
    else:
        gamma_flip = _nearest_flip(gex_profile, spot)
    flip_located = gamma_flip is not None
    distance_to_flip = (spot - gamma_flip) / spot if gamma_flip is not None and spot > 0 else None

    # The curve read at spot. This is the figure the flip, the map and the front
    # end's own live-spot interpolation (gammaRegime.ts) all derive from, so it
    # is reported explicitly rather than left implicit in the chart.
    #
    # It is NOT substituted for `total_net_gex`. That figure is the per-strike
    # sum whose call and put components are also reported, and silently
    # replacing it would leave call_gex_m + put_gex_m != net_gex_m on screen --
    # the same class of internal contradiction this rework exists to remove.
    # The two are different measurements of one quantity (per-strike sum with
    # provider gamma where quoted, vs. the profile's uniform Black-Scholes
    # revaluation); when they diverge materially that is information, so it is
    # surfaced in `notes` instead of averaged away.
    net_gex_profile_m = _interpolate_profile(gex_profile, spot) if gex_profile else None

    # Topography Quadrant Classification
    gex_above_spot = sum(s.net_gex_m for s in strike_exposures if s.strike >= spot)
    gex_below_spot = sum(s.net_gex_m for s in strike_exposures if s.strike < spot)
    denom_gex = max(abs(gex_below_spot), 1e-3)
    gex_ratio = gex_above_spot / denom_gex

    if gamma_flip is None:
        # Every quadrant name is defined relative to S*. Without it there is no
        # quadrant, and the four labels below would each be a coin flip.
        quadrant = "unmeasurable"
        title = "Flip not located"
        desc = (
            "Net dealer gamma does not change sign anywhere in the tested spot range, "
            "so there is no zero-gamma boundary to place spot against."
        )
        action = (
            "Dealer hedging still has a direction (see net GEX), but no regime "
            "boundary exists to trade the crossing of."
        )
        behavior = "Directional read only; no flip-driven trigger on this surface."
    elif spot >= gamma_flip:
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
            behavior = (
                "Directional breakdown cascades; severe volatility expansion and liquidity voids."
            )
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
        call_wall=round(call_wall, 2) if call_wall is not None else None,
        put_wall=round(put_wall, 2) if put_wall is not None else None,
        gamma_flip=round(gamma_flip, 2) if gamma_flip is not None else None,
        volatility_trigger=round(volatility_trigger, 2) if volatility_trigger is not None else None,
        absolute_gamma_peak=(
            round(absolute_gamma_peak, 2) if absolute_gamma_peak is not None else None
        ),
    )

    # Regime Determination.
    #
    # The sign of net dealer gamma IS the regime -- that is what "short gamma"
    # names. The previous rule required `total_net_gex > 0 AND spot > flip` for
    # positive gamma and fell through to "negative_gamma" otherwise, so a
    # chain with firmly positive net GEX printed "negative_gamma" whenever spot
    # sat below the flip, directly contradicting the net GEX figure displayed
    # beside it. Sign decides; the flip band only carves out the neutral zone
    # where the sign is about to change hands.
    gex_scale_m = max((abs(float(pt["net_gex_m"])) for pt in gex_profile), default=0.0)
    neutral_floor = gex_scale_m * _NEUTRAL_GEX_FRACTION
    within_flip_band = distance_to_flip is not None and abs(distance_to_flip) <= _FLIP_BAND_PCT

    if within_flip_band or abs(total_net_gex) <= neutral_floor:
        regime = "neutral_transition"
    elif total_net_gex > 0:
        regime = "positive_gamma"
    else:
        regime = "negative_gamma"
    strength = _regime_strength(total_net_gex, gex_scale_m, distance_to_flip)

    # Total Instantaneous Hedging Flow ($M)
    # F_hedge = GEX_net * (dS/dt) + VEX_net * (dSigma/dt) + CHEX_net
    # Note: ds_dt_pct is a fraction, so GEX ($M per 1%) * ds_dt_pct * 100 is $M.
    #
    # Withheld unless both velocities were actually measured. Feeding assumed
    # velocities in makes this track net GEX and nothing else, which reads as a
    # live flow measurement while being a restatement of the input.
    if ds_dt_pct is None or dvol_dt_pct is None:
        hedging_flow_m: float | None = None
    else:
        hedging_flow_m = (
            (total_net_gex * (ds_dt_pct * 100.0))
            + (total_net_vex * (dvol_dt_pct * 100.0))
            + total_net_chex
        )

    notes = []
    if gamma_flip is not None:
        notes.append(
            f"Gamma Flip Level: ${gamma_flip:.2f} (Spot is {'above' if spot >= gamma_flip else 'below'} flip)"
        )
    else:
        notes.append(
            "No zero-gamma flip in the tested spot range -- net gamma holds one sign throughout."
        )
    notes.append(
        "Call Wall resistance at "
        + (f"${call_wall:.2f}" if call_wall is not None else "n/a (no strikes above spot)")
        + ", Put Wall support at "
        + (f"${put_wall:.2f}" if put_wall is not None else "n/a (no strikes below spot)")
    )
    notes.append(f"Topography: {title} ({behavior})")
    if net_gex_profile_m is not None and gex_scale_m > 0:
        divergence = abs(net_gex_profile_m - total_net_gex) / gex_scale_m
        if divergence > 0.05:
            notes.append(
                f"Per-strike net GEX (${total_net_gex:.1f}M) and the spot-profile read "
                f"(${net_gex_profile_m:.1f}M) differ by {divergence:.0%} of this symbol's gamma "
                "range -- usually provider-quoted gammas disagreeing with the uniform "
                "Black-Scholes revaluation the profile uses."
            )
    if iv_fallback_contracts:
        notes.append(
            f"{iv_fallback_contracts} strike-sides priced off the 20% default IV (no quoted IV); "
            "their Greeks are assumptions, not measurements."
        )
    if zero_dte_put_chex_total > 1.0:
        notes.append(
            f"0DTE Charm decay provides ${zero_dte_put_chex_total:.2f}M afternoon unhedging tailwind"
        )

    return MicrostructureRegimeSnapshot(
        symbol=symbol,
        spot=round(spot, 2),
        asof=asof,
        regime=regime,
        regime_strength=strength,
        net_gex_m=round(total_net_gex, 4),
        call_gex_m=round(total_call_gex, 4),
        put_gex_m=round(total_put_gex, 4),
        net_gex_profile_m=round(net_gex_profile_m, 4) if net_gex_profile_m is not None else None,
        net_vex_m=round(total_net_vex, 4),
        net_chex_m=round(total_net_chex, 4),
        hedging_flow_m=round(hedging_flow_m, 4) if hedging_flow_m is not None else None,
        zero_dte_charm_drift_m=round(zero_dte_put_chex_total, 4),
        gamma_flip=round(gamma_flip, 2) if gamma_flip is not None else None,
        call_wall=round(call_wall, 2) if call_wall is not None else None,
        put_wall=round(put_wall, 2) if put_wall is not None else None,
        volatility_trigger=round(volatility_trigger, 2) if volatility_trigger is not None else None,
        absolute_gamma_peak=(
            round(absolute_gamma_peak, 2) if absolute_gamma_peak is not None else None
        ),
        quality=ChainQuality(
            measurable=True,
            contracts=len(chain_rows),
            strikes=len(strike_exposures),
            total_open_interest=total_oi,
            iv_fallback_contracts=iv_fallback_contracts,
            flip_located=flip_located,
            dealer_convention=dealer_convention,
            reason=None,
        ),
        topography=topography,
        strikes=strike_exposures,
        gex_profile=gex_profile,
        notes=notes,
    )
