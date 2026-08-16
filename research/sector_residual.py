"""Causal 20-day sector-residual momentum panel transform.

All calculations are within one decision date.  The function accepts features
already known at that date and never reads labels, prices, future rows, options,
or holdout data.
"""
from __future__ import annotations


import numpy as np
import pandas as pd


def sector_residual_momentum_20d(
    panel: pd.DataFrame,
    *,
    date_col: str = "timestamp",
    symbol_col: str = "symbol",
    sector_col: str = "sector",
    momentum_col: str = "momentum_20d",
    volatility_col: str = "realized_volatility_20d",
) -> pd.DataFrame:
    """Add fixed-sector leave-one-out residual-momentum signal columns.

    ``sector_residual_score_percentile_20d`` uses the deterministic average-rank
    empirical CDF ``(average_rank - 1) / (n - 1)``; a one-name cross-section is
    assigned 0.5.  Tied names consequently share a percentile and are treated
    identically.  A score is eligible only at <=30th or >=70th percentile and
    only when the symbol has at least one finite-momentum sector peer and a
    positive finite trailing volatility.
    """
    required = {date_col, symbol_col, sector_col, momentum_col, volatility_col}
    missing = required.difference(panel.columns)
    if missing:
        raise KeyError(f"missing required panel columns: {sorted(missing)}")
    result = panel.copy(deep=True)
    if result[[date_col, symbol_col]].isna().any().any():
        raise ValueError("decision date and symbol must be present")
    if result.duplicated([date_col, symbol_col]).any():
        raise ValueError("panel must contain at most one row per decision date and symbol")

    momentum = pd.to_numeric(result[momentum_col], errors="coerce")
    volatility = pd.to_numeric(result[volatility_col], errors="coerce")
    sector_valid = result[sector_col].notna() & result[sector_col].astype(str).str.len().gt(0)
    momentum_valid = np.isfinite(momentum) & sector_valid
    volatility_valid = np.isfinite(volatility) & volatility.gt(0.0)

    working = pd.DataFrame({
        "_date": result[date_col],
        "_sector": result[sector_col].where(sector_valid),
        "_momentum": momentum,
        "_momentum_valid": momentum_valid,
        "_volatility": volatility,
        "_volatility_valid": volatility_valid,
    }, index=result.index)
    valid_momentum = working["_momentum"].where(working["_momentum_valid"], 0.0)
    peer_sum = valid_momentum.groupby([working["_date"], working["_sector"]], dropna=False, sort=False).transform("sum") - valid_momentum
    peer_count = working["_momentum_valid"].astype(int).groupby(
        [working["_date"], working["_sector"]], dropna=False, sort=False
    ).transform("sum") - working["_momentum_valid"].astype(int)

    available = momentum_valid & volatility_valid & peer_count.gt(0)
    residual = pd.Series(0.0, index=result.index, dtype=float)
    residual.loc[available] = (momentum.loc[available] - peer_sum.loc[available] / peer_count.loc[available]).astype(float)
    score = pd.Series(0.0, index=result.index, dtype=float)
    score.loc[available] = residual.loc[available] / volatility.loc[available]

    # Rank only economically available scores.  Neutral scores for unavailable
    # rows must not move an available name across the 30/70 percentile cutoffs.
    # They retain a finite, explicitly neutral 0.5 percentile and abstain.
    # Round only the ranking key, not the exposed score: mathematically equal
    # leave-one-out residuals can otherwise differ at machine precision and
    # defeat the documented average-rank tie rule.
    ranking_score = score.round(12)
    percentile = pd.Series(0.5, index=result.index, dtype=float)
    if available.any():
        available_dates = result.loc[available, date_col]
        available_scores = ranking_score.loc[available]
        date_groups = available_scores.groupby(available_dates, sort=False)
        rank = date_groups.rank(method="average", ascending=True)
        count = date_groups.transform("size")
        percentile.loc[available] = ((rank - 1.0) / (count - 1.0)).where(count.gt(1), 0.5).astype(float)
    eligible = available & ((percentile <= 0.30) | (percentile >= 0.70))

    result["sector_residual_peer_count_20d"] = peer_count.astype(int)
    result["sector_residual_available_20d"] = available.astype(bool)
    result["sector_residual_20d"] = residual
    result["sector_residual_score_20d"] = score
    result["sector_residual_score_percentile_20d"] = percentile
    result["sector_residual_eligible_20d"] = eligible.astype(bool)
    return result
