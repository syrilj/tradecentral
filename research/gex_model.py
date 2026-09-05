"""GEX & Option Exposure Engine.

Computes objective, unbiased scenario-based gamma concentration without assuming fixed
dealer inventory directions (dealers short calls / long puts).

DollarGamma_j = OI_j * 100 * Gamma_j * S^2 * 0.01
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict
import numpy as np
import pandas as pd

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_DEFAULT_RATE = 0.045
_MIN_IV = 0.005
_MIN_TIME_YEARS = 0.5 / 365.25


@dataclass(frozen=True)
class GammaExposureProfile:
    spot_price: float
    total_abs_gamma_usd: float
    call_gamma_usd: float
    put_gamma_usd: float
    gamma_by_strike_distance: Dict[str, float]  # e.g. {"itm": x, "atm": y, "otm": z}
    gamma_by_expiration: Dict[str, float]  # e.g. {"0-7d": x, "8-30d": y, "30d+": z}
    scenario_positive_gex_usd: float  # Uppermost spot move scenario (+2%)
    scenario_negative_gex_usd: float  # Downward spot move scenario (-2%)


def _bs_gamma(
    spot: float,
    strike: float,
    years: float,
    iv: float,
    rate: float = _DEFAULT_RATE,
) -> float:
    """Calculate Black-Scholes Gamma d^2V / dS^2."""
    if spot <= 0 or strike <= 0 or years <= 0 or iv < _MIN_IV:
        return 0.0
    tau = max(years, _MIN_TIME_YEARS)
    root_t = math.sqrt(tau)
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * tau) / (iv * root_t)
    phi_d1 = math.exp(-0.5 * d1 * d1) / _SQRT_2PI
    return phi_d1 / (spot * iv * root_t)


def compute_dollar_gamma(
    open_interest: float,
    gamma: float,
    spot_price: float,
) -> float:
    """DollarGamma_j = OI_j * 100 * Gamma_j * S^2 * 0.01."""
    if open_interest <= 0 or gamma <= 0 or spot_price <= 0 or not np.isfinite(open_interest):
        return 0.0
    return float(open_interest * 100.0 * gamma * (spot_price**2) * 0.01)


def compute_unbiased_gex_profile(
    option_chain: pd.DataFrame,
    spot_price: float,
    rate: float = _DEFAULT_RATE,
) -> GammaExposureProfile:
    """Calculates unbiased gamma exposure metrics from an option chain DataFrame.

    Expected columns: ["strike", "option_type", "open_interest", "gamma", "days_to_expiration"]
    Uses true Black-Scholes scenario revaluation under +/- 2% spot shocks.
    """
    if option_chain.empty or spot_price <= 0:
        return GammaExposureProfile(
            spot_price=spot_price,
            total_abs_gamma_usd=0.0,
            call_gamma_usd=0.0,
            put_gamma_usd=0.0,
            gamma_by_strike_distance={"itm": 0.0, "atm": 0.0, "otm": 0.0},
            gamma_by_expiration={"0-7d": 0.0, "8-30d": 0.0, "30d+": 0.0},
            scenario_positive_gex_usd=0.0,
            scenario_negative_gex_usd=0.0,
        )

    chain = option_chain.copy()

    # Robust column resolution
    if "strike" in chain.columns:
        strikes = pd.to_numeric(chain["strike"], errors="coerce").fillna(0.0)
    elif "strike_price" in chain.columns:
        strikes = pd.to_numeric(chain["strike_price"], errors="coerce").fillna(0.0)
    elif "k" in chain.columns:
        strikes = pd.to_numeric(chain["k"], errors="coerce").fillna(0.0)
    else:
        strikes = pd.Series(0.0, index=chain.index)
    chain["strike"] = strikes

    if "open_interest" in chain.columns:
        ois = pd.to_numeric(chain["open_interest"], errors="coerce").fillna(0.0)
    elif "oi" in chain.columns:
        ois = pd.to_numeric(chain["oi"], errors="coerce").fillna(0.0)
    else:
        ois = pd.Series(0.0, index=chain.index)
    chain["open_interest"] = ois

    if "gamma" in chain.columns:
        gammas = pd.to_numeric(chain["gamma"], errors="coerce").fillna(0.0)
    elif "g" in chain.columns:
        gammas = pd.to_numeric(chain["g"], errors="coerce").fillna(0.0)
    else:
        gammas = pd.Series(0.0, index=chain.index)
    chain["gamma"] = gammas

    if "days_to_expiration" in chain.columns:
        dtes = pd.to_numeric(chain["days_to_expiration"], errors="coerce").fillna(30.0)
    elif "dte" in chain.columns:
        dtes = pd.to_numeric(chain["dte"], errors="coerce").fillna(30.0)
    else:
        dtes = pd.Series(30.0, index=chain.index)
    chain["days_to_expiration"] = dtes

    if "implied_volatility" in chain.columns:
        ivs = pd.to_numeric(chain["implied_volatility"], errors="coerce").fillna(0.25)
    elif "iv" in chain.columns:
        ivs = pd.to_numeric(chain["iv"], errors="coerce").fillna(0.25)
    else:
        ivs = pd.Series(0.25, index=chain.index)
    chain["implied_volatility"] = ivs

    if "option_type" in chain.columns:
        opt_types = chain["option_type"].astype(str).str.upper()
    elif "right" in chain.columns:
        opt_types = chain["right"].astype(str).str.upper()
    elif "type" in chain.columns:
        opt_types = chain["type"].astype(str).str.upper()
    else:
        opt_types = pd.Series("CALL", index=chain.index)
    chain["option_type"] = opt_types

    # Base Dollar Gamma at current spot
    dollar_gammas = []
    for oi, g, k, dte, iv in zip(ois, gammas, strikes, dtes, ivs):
        if oi > 0 and g > 0:
            dg = compute_dollar_gamma(oi, g, spot_price)
        elif oi > 0 and k > 0 and iv >= _MIN_IV:
            tau = max(dte, 0.5) / 365.25
            calc_g = _bs_gamma(spot=spot_price, strike=k, years=tau, iv=iv, rate=rate)
            dg = compute_dollar_gamma(oi, calc_g, spot_price)
        else:
            dg = 0.0
        dollar_gammas.append(dg)

    chain["dollar_gamma"] = dollar_gammas
    total_abs_gex = float(chain["dollar_gamma"].sum())

    is_call = chain["option_type"].str.contains("C")
    is_put = chain["option_type"].str.contains("P")

    call_gex = float(chain.loc[is_call, "dollar_gamma"].sum())
    put_gex = float(chain.loc[is_put, "dollar_gamma"].sum())

    # Strike distance breakdown relative to spot_price
    dist_pct = (chain["strike"] - spot_price) / spot_price
    atm_mask = dist_pct.abs() <= 0.02
    otm_call_mask = is_call & (dist_pct > 0.02)
    otm_put_mask = is_put & (dist_pct < -0.02)
    itm_mask = ~atm_mask & ~otm_call_mask & ~otm_put_mask

    gamma_by_strike = {
        "atm": float(chain.loc[atm_mask, "dollar_gamma"].sum()),
        "otm": float(chain.loc[otm_call_mask | otm_put_mask, "dollar_gamma"].sum()),
        "itm": float(chain.loc[itm_mask, "dollar_gamma"].sum()),
    }

    # Expiration breakdown
    dte = chain["days_to_expiration"]
    gamma_by_exp = {
        "0-7d": float(chain.loc[dte <= 7, "dollar_gamma"].sum()),
        "8-30d": float(chain.loc[(dte > 7) & (dte <= 30), "dollar_gamma"].sum()),
        "30d+": float(chain.loc[dte > 30, "dollar_gamma"].sum()),
    }

    # True Black-Scholes scenario revaluation under +/- 2% spot shocks
    spot_up = spot_price * 1.02
    spot_down = spot_price * 0.98
    scen_pos = 0.0
    scen_neg = 0.0

    for oi, k, d, iv in zip(ois, strikes, dtes, ivs):
        if oi > 0 and k > 0 and iv >= _MIN_IV:
            tau = max(d, 0.5) / 365.25
            g_up = _bs_gamma(spot=spot_up, strike=k, years=tau, iv=iv, rate=rate)
            g_down = _bs_gamma(spot=spot_down, strike=k, years=tau, iv=iv, rate=rate)
            scen_pos += compute_dollar_gamma(oi, g_up, spot_up)
            scen_neg += compute_dollar_gamma(oi, g_down, spot_down)

    return GammaExposureProfile(
        spot_price=spot_price,
        total_abs_gamma_usd=total_abs_gex,
        call_gamma_usd=call_gex,
        put_gamma_usd=put_gex,
        gamma_by_strike_distance=gamma_by_strike,
        gamma_by_expiration=gamma_by_exp,
        scenario_positive_gex_usd=float(scen_pos),
        scenario_negative_gex_usd=float(scen_neg),
    )
