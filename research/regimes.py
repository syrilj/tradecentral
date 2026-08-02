"""Causal regime labels and simple per-regime evidence summaries."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def classify_regimes(
    prices: pd.Series | pd.DataFrame,
    *,
    close_col: str = "close",
    volatility_window: int = 20,
    trend_window: int = 60,
    bear_drawdown: float = -0.15,
) -> pd.DataFrame:
    """Return trailing-only volatility, trend, and drawdown regime labels."""
    if volatility_window < 2 or trend_window < 2 or bear_drawdown >= 0:
        raise ValueError("invalid causal regime configuration")
    close = prices[close_col] if isinstance(prices, pd.DataFrame) else prices
    close = pd.to_numeric(close, errors="coerce").astype(float)
    if not close.index.is_monotonic_increasing or close.index.has_duplicates:
        raise ValueError("prices must have a unique ascending index")
    returns = close.pct_change(fill_method=None)
    volatility = returns.rolling(volatility_window, min_periods=volatility_window).std(ddof=1)
    low, high = volatility.expanding(min_periods=volatility_window).quantile(1 / 3), volatility.expanding(min_periods=volatility_window).quantile(2 / 3)
    volatility_regime = pd.Series(pd.NA, index=close.index, dtype="string")
    valid_vol = volatility.notna() & low.notna() & high.notna()
    volatility_regime.loc[valid_vol & (volatility <= low)] = "LOW"
    volatility_regime.loc[valid_vol & (volatility > low) & (volatility <= high)] = "MEDIUM"
    volatility_regime.loc[valid_vol & (volatility > high)] = "HIGH"

    ma = close.rolling(trend_window, min_periods=trend_window).mean()
    trend_regime = pd.Series(pd.NA, index=close.index, dtype="string")
    trend_regime.loc[ma.notna() & (close > ma)] = "UP"
    trend_regime.loc[ma.notna() & (close < ma)] = "DOWN"
    trend_regime.loc[ma.notna() & (close == ma)] = "FLAT"
    drawdown = close.div(close.cummax()).sub(1.0)
    bear_market = (drawdown <= bear_drawdown).astype("boolean")
    bear_market.loc[close.isna()] = pd.NA
    return pd.DataFrame(
        {
            "realized_volatility": volatility,
            "volatility_regime": volatility_regime,
            "trend_regime": trend_regime,
            "drawdown": drawdown,
            "bear_market": bear_market,
        },
        index=close.index,
    )


def slice_by_regime(records: pd.DataFrame, regime_columns: Iterable[str] = ("volatility_regime", "trend_regime", "bear_market")) -> dict[tuple[object, ...], pd.DataFrame]:
    """Partition evidence rows by the selected regime columns without mutation."""
    cols = tuple(regime_columns)
    missing = set(cols).difference(records.columns)
    if missing:
        raise KeyError(f"missing regime columns: {sorted(missing)}")
    return {key if isinstance(key, tuple) else (key,): group.copy() for key, group in records.groupby(list(cols), dropna=False, sort=True)}


def performance_by_regime(
    records: pd.DataFrame,
    *,
    return_col: str = "net_return",
    regime_columns: Iterable[str] = ("volatility_regime", "trend_regime", "bear_market"),
) -> pd.DataFrame:
    """Summarise observations, mean return, and win rate for each regime slice."""
    if return_col not in records:
        raise KeyError(f"missing return column: {return_col}")
    cols = list(regime_columns)
    if not cols:
        raise ValueError("at least one regime column is required")
    values = pd.to_numeric(records[return_col], errors="coerce")
    frame = records.loc[:, cols].copy()
    frame[return_col] = values
    grouped = frame.groupby(cols, dropna=False, sort=True)[return_col]
    return grouped.agg(n="count", mean_return="mean", median_return="median").assign(win_rate=grouped.apply(lambda x: float((x > 0).mean()) if len(x) else np.nan)).reset_index()
