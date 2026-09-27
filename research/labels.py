"""Frozen multi-trading-day labels for daily directional research."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

FROZEN_HORIZONS: tuple[int, ...] = (5, 10, 20)


def _validate_horizons(horizons: Iterable[int]) -> tuple[int, ...]:
    result = tuple(int(h) for h in horizons)
    if not result or any(h <= 0 for h in result) or len(set(result)) != len(result):
        raise ValueError("horizons must be unique positive trading-day counts")
    return result


def directional_labels(
    prices: pd.Series | pd.DataFrame,
    *,
    close_col: str = "close",
    horizons: Iterable[int] = FROZEN_HORIZONS,
) -> pd.DataFrame:
    """Create labels at each close using only a row-count trading calendar.

    At origin ``t``, the h-day target is ``close[t + h] / close[t] - 1``.  No
    calendar-day offsets are used: a holiday never shortens the 5/10/20 trading
    day horizons.  Trailing origins without a complete outcome stay missing.
    """
    hs = _validate_horizons(horizons)
    if isinstance(prices, pd.DataFrame):
        if close_col not in prices.columns:
            raise KeyError(f"missing close column: {close_col}")
        close = prices[close_col].copy()
    else:
        close = prices.copy()
    if not close.index.is_monotonic_increasing:
        raise ValueError("prices must be sorted in ascending time order")
    if close.index.has_duplicates:
        raise ValueError("prices index must not contain duplicate sessions")
    close = pd.to_numeric(close, errors="coerce").astype(float)
    if (close.dropna() <= 0).any():
        raise ValueError("close prices must be positive")

    result = pd.DataFrame(index=close.index)
    for h in hs:
        target = close.shift(-h)
        forward_return = target.div(close).sub(1.0)
        result[f"target_end_{h}d"] = target.index.to_series().shift(-h).reindex(close.index)
        result[f"forward_return_{h}d"] = forward_return
        result[f"direction_{h}d"] = pd.array(
            np.where(forward_return.notna(), (forward_return > 0.0).astype(int), pd.NA),
            dtype="Int64",
        )
    return result


def tradable_directional_labels(
    bars: pd.DataFrame,
    *,
    horizons: Iterable[int] = FROZEN_HORIZONS,
) -> pd.DataFrame:
    """Build targets executable after a signal formed at the prior close.

    A decision row at session ``t`` enters at that session's open.  The h-day
    exit is the close of session ``t + h - 1``.  Callers pair these labels with
    features shifted forward one session, so decision-day data is unavailable
    to the forecast.
    """
    hs = _validate_horizons(horizons)
    missing = {"open", "close"}.difference(bars.columns)
    if missing:
        raise KeyError(f"missing tradable label columns: {sorted(missing)}")
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError("bars must have a unique ascending trading-date index")
    entry = pd.to_numeric(bars["open"], errors="coerce").astype(float)
    close = pd.to_numeric(bars["close"], errors="coerce").astype(float)
    if (entry.dropna() <= 0).any() or (close.dropna() <= 0).any():
        raise ValueError("open and close prices must be positive")
    result = pd.DataFrame(index=bars.index)
    result["entry_open"] = entry
    for horizon in hs:
        shift = -(horizon - 1)
        exit_close = close.shift(shift)
        target_end = bars.index.to_series().shift(shift).reindex(bars.index)
        forward_return = exit_close.div(entry).sub(1.0)
        result[f"target_end_{horizon}d"] = target_end
        result[f"target_close_{horizon}d"] = exit_close
        result[f"forward_return_{horizon}d"] = forward_return
        result[f"direction_{horizon}d"] = pd.array(
            np.where(forward_return.notna(), (forward_return > 0.0).astype(int), pd.NA),
            dtype="Int64",
        )
    return result


def valid_label_origins(labels: pd.DataFrame, horizon_days: int) -> pd.Index:
    """Return origins whose frozen target has fully resolved."""
    key = f"direction_{int(horizon_days)}d"
    if key not in labels:
        raise KeyError(f"missing frozen label column: {key}")
    return labels.index[labels[key].notna()]
