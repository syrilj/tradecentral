"""Causal daily features for frozen 5/10/20-session directional research."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .labels import FROZEN_HORIZONS

# Below this many rows, "every value is identical" cannot be told apart from
# an unlucky small sample -- see `assert_no_degenerate_feature_columns`.
MIN_ROWS_TO_CHECK_DEGENERACY = 3


def assert_no_degenerate_feature_columns(
    features: pd.DataFrame, *, min_rows: int = MIN_ROWS_TO_CHECK_DEGENERACY,
) -> None:
    """Fail the run if any column is all-null or has zero variance.

    This is the systemic control behind one specific, already-shipped bug:
    `build_pead_factor_hybrid.py` looked for FINRA short-volume data at a
    path that never existed, the miss was swallowed by `except Exception:
    pass`, and `short_pressure` silently collapsed to the constant multiplier
    0.5 for the entire run -- while `GATE_PEAD_HYBRID_RESULT.md` went on
    being generated as though the feature were included. See
    `edge/docs/LOOKAHEAD_CORRECTION.md`. A loader that raises instead of
    returning `None` (see `edge/tools/data_sources.py`) closes that one
    incident; this function closes the class -- any feature pipeline that
    calls it can no longer hand a model a column that carries zero
    information without the run stopping to say so, regardless of *why* the
    column went flat.

    A column is degenerate when, after dropping nulls:
      - nothing is left (all-null), or
      - only one distinct value remains (constant / zero-variance).

    Both conditions name the offending column in the raised message, since
    "some column somewhere is broken" is not actionable at pipeline scale.

    Edge cases, deliberately:
      - Frames with fewer than `min_rows` rows are not checked at all and
        never raise. With 1 row, every column is trivially "constant" --
        there is nothing to compare it to -- and that is not evidence of a
        bug. With 2 rows, two matching values are indistinguishable from an
        unlucky coincidence. Flagging either would be a false positive, not
        a caught bug, so this function stays silent below the threshold
        rather than guessing.
      - A genuinely binary 0/1 column is never degenerate: it has two
        distinct non-null values, so the "one distinct value" test does not
        fire. This function counts *distinct values*, not range, spread, or
        any notion of "how binary-looking" a column is -- it cannot mistake
        a real two-valued signal for a constant.
    """
    if not isinstance(features, pd.DataFrame):
        raise TypeError("features must be a DataFrame")
    if len(features) < min_rows:
        return
    for column in features.columns:
        series = features[column]
        non_null = series.dropna()
        if non_null.empty:
            raise ValueError(
                f"feature column {column!r} is all-null across {len(series)} rows. "
                "A data source most likely failed to load and the failure was "
                "handled by silently producing 'no signal' instead of raising -- "
                "this is the systemic shape of the short_pressure incident in "
                "edge/docs/LOOKAHEAD_CORRECTION.md."
            )
        if non_null.nunique(dropna=True) <= 1:
            raise ValueError(
                f"feature column {column!r} is constant (value={non_null.iloc[0]!r}) "
                f"across all {len(non_null)} non-null of {len(series)} rows -- zero "
                "variance, so it can contribute nothing to any model that consumes "
                "it. This is exactly how `short_pressure` went undetected "
                "(edge/docs/LOOKAHEAD_CORRECTION.md): a missing data source degraded "
                "silently to a constant instead of failing the run."
            )


def _validate_panel(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(bars.columns)
    if missing:
        raise KeyError(f"bars missing required columns: {', '.join(sorted(missing))}")
    if not isinstance(bars.index, pd.MultiIndex) or bars.index.nlevels != 2:
        raise ValueError("bars must use a (timestamp, symbol) MultiIndex")
    if list(bars.index.names) != ["timestamp", "symbol"]:
        bars = bars.copy()
        bars.index = bars.index.set_names(["timestamp", "symbol"])
    if not bars.index.is_monotonic_increasing or bars.index.has_duplicates:
        raise ValueError("bars panel must be sorted and have unique timestamp/symbol rows")
    return bars.loc[:, ["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").copy()


def causal_daily_features(bars: pd.DataFrame, *, horizons: Iterable[int] = FROZEN_HORIZONS,
                          volatility_window: int = 20) -> pd.DataFrame:
    """Build backwards-looking features only.

    Each row at session ``t`` uses values at or before ``t``.  This function
    deliberately does not join forward labels; callers must do that only after
    train/test splitting.
    """
    hs = tuple(int(horizon) for horizon in horizons)
    if hs != FROZEN_HORIZONS:
        raise ValueError(f"research horizons are frozen to {FROZEN_HORIZONS}")
    if volatility_window < 2:
        raise ValueError("volatility_window must be at least two")
    panel = _validate_panel(bars)
    rows: list[pd.DataFrame] = []
    for symbol, frame in panel.groupby(level="symbol", sort=True):
        frame = frame.droplevel("symbol")
        close = frame["close"].astype(float)
        returns = close.pct_change()
        volatility = returns.rolling(volatility_window, min_periods=volatility_window).std(ddof=0)
        result = pd.DataFrame(index=frame.index)
        result["realized_volatility_20d"] = volatility
        result["close_to_sma_20d"] = close.div(close.rolling(20, min_periods=20).mean()).sub(1.0)
        volume_mean = frame["volume"].rolling(20, min_periods=20).mean()
        volume_std = frame["volume"].rolling(20, min_periods=20).std(ddof=0).replace(0.0, np.nan)
        result["volume_z_20d"] = frame["volume"].sub(volume_mean).div(volume_std)
        for horizon in hs:
            momentum = close.div(close.shift(horizon)).sub(1.0)
            result[f"momentum_{horizon}d"] = momentum
            result[f"volatility_scaled_momentum_{horizon}d"] = momentum.div(volatility.replace(0.0, np.nan))
        result["symbol"] = symbol
        rows.append(result.reset_index().set_index(["timestamp", "symbol"]))
    panel = pd.concat(rows).sort_index()
    # Checked across the full panel (all symbols, all dates), not per symbol:
    # a single short or quiet symbol legitimately produces a lot of NaN/flat
    # rows during warm-up, but the whole panel going flat on one column is
    # the shape of a silently-broken input, not a quiet one.
    assert_no_degenerate_feature_columns(panel)
    return panel


def feature_columns(*, horizons: Iterable[int] = FROZEN_HORIZONS) -> tuple[str, ...]:
    """The fixed simple-model feature order; no data-dependent selection."""
    hs = tuple(int(horizon) for horizon in horizons)
    if hs != FROZEN_HORIZONS:
        raise ValueError(f"research horizons are frozen to {FROZEN_HORIZONS}")
    return ("realized_volatility_20d", "close_to_sma_20d", "volume_z_20d",
            *(f"momentum_{horizon}d" for horizon in hs),
            *(f"volatility_scaled_momentum_{horizon}d" for horizon in hs))
