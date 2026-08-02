"""Supplemental OOF-only robustness diagnostics for underlying research.

These diagnostics are not promotion criteria, option-profitability evidence, or
live-portfolio drawdown estimates.  They deliberately consume supplied
development OOF rows only and refuse rows marked as terminal holdout data.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .statistics import date_block_bootstrap_ci


DEFAULT_ROUND_TRIP_COST_STRESSES_BPS: tuple[float, ...] = (10.0, 20.0, 30.0)


def _series_from_column_or_index(rows: pd.DataFrame, field: str) -> pd.Series:
    if field in rows.columns:
        return rows[field].copy()
    if isinstance(rows.index, pd.MultiIndex) and field in rows.index.names:
        return pd.Series(rows.index.get_level_values(field), index=rows.index)
    if rows.index.name == field or (field == "timestamp" and isinstance(rows.index, pd.DatetimeIndex)):
        return pd.Series(rows.index, index=rows.index)
    raise KeyError(f"OOF rows are missing required field: {field}")


def _reject_terminal_holdout(rows: pd.DataFrame) -> None:
    """Reject explicit holdout markers rather than silently mixing evidence."""
    for field in ("partition", "split", "dataset_partition", "source_partition"):
        if field in rows.columns:
            values = rows[field].astype("string").str.lower()
            if values.str.contains("holdout", na=False).any():
                raise ValueError("terminal holdout rows are not valid robustness input")
    if "terminal_holdout" in rows.columns and rows["terminal_holdout"].fillna(False).astype(bool).any():
        raise ValueError("terminal holdout rows are not valid robustness input")


def _validate_cost_stresses(values: Iterable[float]) -> tuple[float, ...]:
    stresses = tuple(float(value) for value in values)
    if not stresses or len(set(stresses)) != len(stresses):
        raise ValueError("cost stresses must be non-empty and unique")
    if any(not math.isfinite(value) or value < 0 for value in stresses):
        raise ValueError("cost stresses must be finite non-negative bps")
    return stresses


def _positive_pnl_concentration(frame: pd.DataFrame, *, group: pd.Series,
                                threshold: float) -> dict[str, Any]:
    work = pd.DataFrame({"group": group.astype("string").fillna("<missing>"),
                         "positive_pnl": frame["net_return"].clip(lower=0.0)}, index=frame.index)
    grouped = work.groupby("group", sort=True, dropna=False)["positive_pnl"].sum()
    total = float(grouped.sum())
    groups = [{"group": str(name), "positive_pnl": float(value),
               "positive_pnl_share": float(value / total) if total > 0 else 0.0}
              for name, value in grouped.items()]
    largest_share = max((entry["positive_pnl_share"] for entry in groups), default=0.0)
    return {"positive_pnl_total": total, "largest_positive_pnl_share": largest_share,
            "concentration_threshold": threshold, "flagged": bool(total > 0 and largest_share > threshold),
            "groups": groups}


def oof_underlying_robustness_diagnostics(
    oof_rows: pd.DataFrame,
    *,
    date_col: str = "timestamp",
    gross_return_col: str = "gross_return",
    position_col: str = "position",
    symbol_col: str = "symbol",
    regime_col: str = "volatility_regime",
    round_trip_cost_stresses_bps: Iterable[float] = DEFAULT_ROUND_TRIP_COST_STRESSES_BPS,
    concentration_threshold: float = 0.50,
    block_size: int = 5,
    n_bootstrap: int = 2_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Stress development OOF underlying expectancy with date-aware inference.

    ``gross_return`` must already be the signed underlying return at the OOF
    origin.  Each stress subtracts the stated *round-trip* bps from active
    positions only.  The bootstrap aggregates by decision/trading date before
    resampling, preventing cross-sectional rows from being treated as IID.
    """
    if oof_rows.empty:
        raise ValueError("OOF rows must not be empty")
    if not 0.0 < concentration_threshold <= 1.0:
        raise ValueError("concentration_threshold must be in (0, 1]")
    _reject_terminal_holdout(oof_rows)
    stresses = _validate_cost_stresses(round_trip_cost_stresses_bps)
    dates = pd.to_datetime(_series_from_column_or_index(oof_rows, date_col), errors="coerce")
    gross = pd.to_numeric(_series_from_column_or_index(oof_rows, gross_return_col), errors="coerce")
    position = pd.to_numeric(_series_from_column_or_index(oof_rows, position_col), errors="coerce")
    symbol = _series_from_column_or_index(oof_rows, symbol_col)
    regime = _series_from_column_or_index(oof_rows, regime_col)
    if dates.isna().any() or gross.isna().any() or position.isna().any() or not np.isfinite(gross).all():
        raise ValueError("OOF rows require finite gross returns, positions, and trading dates")
    if not position.isin((-1, 0, 1)).all():
        raise ValueError("OOF positions must be exactly -1, 0, or 1")
    if (position.eq(0) & ~np.isclose(gross, 0.0)).any():
        raise ValueError("flat OOF positions must have zero gross return")
    base = pd.DataFrame({"trading_date": dates.dt.normalize(), "gross_return": gross.astype(float),
                         "position": position.astype(int), "symbol": symbol, "regime": regime}, index=oof_rows.index)
    active = base["position"].ne(0)
    diagnostics: list[dict[str, Any]] = []
    for stress in stresses:
        frame = base.copy()
        frame["net_return"] = frame["gross_return"] - np.where(active, stress / 10_000.0, 0.0)
        ci = date_block_bootstrap_ci(frame["net_return"], frame["trading_date"], confidence=.95,
                                     block_size=block_size, n_bootstrap=n_bootstrap, seed=seed)
        diagnostics.append({
            "round_trip_cost_bps": stress,
            "oof_rows": int(len(frame)),
            "active_rows": int(active.sum()),
            "date_aggregated_net_expectancy": float(ci.estimate),
            "date_block_bootstrap_ci95": {"lower": float(ci.lower), "upper": float(ci.upper),
                                            "n_dates": int(ci.n_dates), "block_size": int(ci.block_size)},
            "symbol_positive_pnl_concentration": _positive_pnl_concentration(frame, group=frame["symbol"],
                                                                                threshold=concentration_threshold),
            "regime_positive_pnl_concentration": _positive_pnl_concentration(frame, group=frame["regime"],
                                                                                threshold=concentration_threshold),
        })
    return {
        "schema_version": "edge-oof-underlying-robustness-v1",
        "scope": "development_oof_underlying_supplemental_diagnostic",
        "supplemental_only": True,
        "option_profitability": "not_evaluated",
        "live_portfolio_drawdown": "not_evaluated",
        "promotion_criteria": "unchanged",
        "cost_stresses": diagnostics,
    }
