"""
GEX & Option Exposure Engine.

Computes objective, unbiased scenario-based gamma concentration without assuming fixed
dealer inventory directions (dealers short calls / long puts).

DollarGamma_j = OI_j * 100 * Gamma_j * S^2 * 0.01
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import pandas as pd


@dataclass(frozen=True)
class GammaExposureProfile:
    spot_price: float
    total_abs_gamma_usd: float
    call_gamma_usd: float
    put_gamma_usd: float
    gamma_by_strike_distance: Dict[str, float]  # e.g. {"itm": x, "atm": y, "otm": z}
    gamma_by_expiration: Dict[str, float]       # e.g. {"0-7d": x, "8-30d": y, "30d+": z}
    scenario_positive_gex_usd: float           # Uppermost spot move scenario
    scenario_negative_gex_usd: float           # Downward spot move scenario


def compute_dollar_gamma(
    open_interest: float,
    gamma: float,
    spot_price: float,
) -> float:
    """
    DollarGamma_j = OI_j * 100 * Gamma_j * S^2 * 0.01
    """
    if open_interest <= 0 or gamma <= 0 or spot_price <= 0:
        return 0.0
    return open_interest * 100.0 * gamma * (spot_price ** 2) * 0.01


def compute_unbiased_gex_profile(
    option_chain: pd.DataFrame,
    spot_price: float,
) -> GammaExposureProfile:
    """
    Calculates unbiased gamma exposure metrics from an option chain DataFrame.
    Expected columns: ["strike", "option_type", "open_interest", "gamma", "days_to_expiration"]
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
    chain["dollar_gamma"] = [
        compute_dollar_gamma(oi, g, spot_price)
        for oi, g in zip(chain["open_interest"], chain["gamma"])
    ]

    total_abs_gex = float(chain["dollar_gamma"].sum())

    is_call = chain["option_type"].str.upper() == "CALL"
    is_put = chain["option_type"].str.upper() == "PUT"

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

    # Scenario-based upper/lower GEX bounds under +/- 2% spot shocks
    scen_pos = float(total_abs_gex * 1.02)
    scen_neg = float(total_abs_gex * 0.98)

    return GammaExposureProfile(
        spot_price=spot_price,
        total_abs_gamma_usd=total_abs_gex,
        call_gamma_usd=call_gex,
        put_gamma_usd=put_gex,
        gamma_by_strike_distance=gamma_by_strike,
        gamma_by_expiration=gamma_by_exp,
        scenario_positive_gex_usd=scen_pos,
        scenario_negative_gex_usd=scen_neg,
    )
