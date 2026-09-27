"""Fixed causal feature hypotheses for directional underlying research.

The functions here only transform historical OHLCV bars at each close.  They
do not access labels, outcomes, options, model fitting, or holdout boundaries.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


SHOCK_REVERSAL_HORIZON_DAYS = 5
SHOCK_REVERSAL_VOLATILITY_SESSIONS = 20
SHOCK_REVERSAL_ABS_THRESHOLD = 1.5


def _daily_ohlcv_panel(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(bars.columns))
    if missing:
        raise KeyError(f"bars missing required columns: {', '.join(missing)}")
    if not isinstance(bars.index, pd.MultiIndex) or bars.index.nlevels != 2:
        raise ValueError("bars must use a (timestamp, symbol) MultiIndex")
    panel = bars.copy()
    if list(panel.index.names) != ["timestamp", "symbol"]:
        panel.index = panel.index.set_names(["timestamp", "symbol"])
    if not panel.index.is_monotonic_increasing or panel.index.has_duplicates:
        raise ValueError("bars panel must be sorted and have unique timestamp/symbol rows")
    panel = panel.loc[:, ["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if panel["close"].isna().any() or (panel["close"] <= 0).any():
        raise ValueError("close prices must be finite positive values")
    return panel


def shock_reversal_features_5d(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute the preregistered one-day shock-reversal score at each close.

    A shock is the one-session close return divided by trailing 20-return
    realized daily volatility.  The score is its negative: a positive shock
    becomes a bearish 5-day reversal hypothesis and vice versa.  The fixed
    eligibility boundary is |shock| >= 1.5, with undefined/zero-volatility
    observations conservatively ineligible.
    """
    panel = _daily_ohlcv_panel(bars)
    rows: list[pd.DataFrame] = []
    for symbol, frame in panel.groupby(level="symbol", sort=True):
        close = frame.droplevel("symbol")["close"].astype(float)
        return_1d = close.pct_change(fill_method=None)
        volatility = return_1d.rolling(SHOCK_REVERSAL_VOLATILITY_SESSIONS,
                                       min_periods=SHOCK_REVERSAL_VOLATILITY_SESSIONS).std(ddof=0)
        shock = return_1d.div(volatility.replace(0.0, np.nan))
        result = pd.DataFrame(index=close.index)
        result["return_1d"] = return_1d
        result["realized_daily_volatility_20d"] = volatility
        result["shock_1d"] = shock
        result["shock_reversal_score_5d"] = -shock
        result["shock_reversal_eligible_5d"] = (shock.abs() >= SHOCK_REVERSAL_ABS_THRESHOLD).fillna(False).astype(bool)
        result["symbol"] = symbol
        rows.append(result.reset_index().set_index(["timestamp", "symbol"]))
    return pd.concat(rows).sort_index()
