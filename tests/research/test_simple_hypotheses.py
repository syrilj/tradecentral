from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.simple_hypotheses import (
    SHOCK_REVERSAL_ABS_THRESHOLD,
    SHOCK_REVERSAL_HORIZON_DAYS,
    SHOCK_REVERSAL_VOLATILITY_SESSIONS,
    shock_reversal_features_5d,
)


def _panel(n: int = 50) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=n)
    close = 100 * np.exp(np.linspace(0, .08, n) + .003 * np.sin(np.arange(n)))
    rows = []
    for symbol, multiplier in (("AAA", 1.0), ("BBB", 2.0)):
        frame = pd.DataFrame({"open": close * multiplier, "high": close * multiplier * 1.01,
                              "low": close * multiplier * .99, "close": close * multiplier,
                              "volume": 1_000 + np.arange(n), "symbol": symbol}, index=dates)
        rows.append(frame.reset_index(names="timestamp").set_index(["timestamp", "symbol"]))
    return pd.concat(rows).sort_index()


def test_shock_reversal_is_fixed_causal_and_has_explicit_5d_outputs() -> None:
    features = shock_reversal_features_5d(_panel())
    assert SHOCK_REVERSAL_HORIZON_DAYS == 5
    assert SHOCK_REVERSAL_VOLATILITY_SESSIONS == 20
    assert SHOCK_REVERSAL_ABS_THRESHOLD == 1.5
    assert {"shock_reversal_score_5d", "shock_reversal_eligible_5d"}.issubset(features.columns)
    valid = features.dropna(subset=["shock_1d"])
    assert (valid["shock_reversal_score_5d"] == -valid["shock_1d"]).all()
    assert (valid["shock_reversal_eligible_5d"] == (valid["shock_1d"].abs() >= 1.5)).all()
    assert not features["shock_reversal_eligible_5d"].iloc[:20].any()


def test_future_mutation_cannot_change_prior_shock_reversal_features() -> None:
    bars = _panel()
    before = shock_reversal_features_5d(bars)
    cutoff = pd.Timestamp("2025-02-28")
    changed = bars.copy()
    changed.loc[changed.index.get_level_values("timestamp") > cutoff, "close"] *= 10
    after = shock_reversal_features_5d(changed)
    pd.testing.assert_frame_equal(before.loc[(slice(None, cutoff), slice(None)), :],
                                  after.loc[(slice(None, cutoff), slice(None)), :])


def test_zero_volatility_is_ineligible_and_unsorted_panel_fails_closed() -> None:
    bars = _panel()
    bars.loc[(slice(None), "AAA"), "close"] = 100.0
    result = shock_reversal_features_5d(bars)
    assert not result.xs("AAA", level="symbol")["shock_reversal_eligible_5d"].any()
    with pytest.raises(ValueError, match="sorted"):
        shock_reversal_features_5d(_panel().iloc[::-1])
