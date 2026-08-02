from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.labels import (
    FROZEN_HORIZONS,
    directional_labels,
    tradable_directional_labels,
    valid_label_origins,
)


def _prices(n: int = 35) -> pd.Series:
    # Business-day sessions intentionally cross a weekend; horizons are row based.
    return pd.Series(np.arange(100.0, 100.0 + n), index=pd.bdate_range("2024-01-02", periods=n), name="close")


def test_frozen_horizons_are_daily_and_have_complete_targets_only() -> None:
    prices = _prices()
    labels = directional_labels(prices)
    assert FROZEN_HORIZONS == (5, 10, 20)
    assert labels.loc[prices.index[0], "forward_return_5d"] == pytest.approx(5 / 100)
    assert labels.loc[prices.index[0], "target_end_5d"] == prices.index[5]
    assert labels.loc[prices.index[0], "direction_20d"] == 1
    assert labels["forward_return_20d"].tail(20).isna().all()
    assert len(valid_label_origins(labels, 10)) == len(prices) - 10


def test_future_mutation_does_not_change_resolved_prior_labels() -> None:
    prices = _prices(45)
    before = directional_labels(prices)
    mutated = prices.copy()
    # Outcomes after this date cannot affect labels whose target endpoint is before it.
    mutated.iloc[30:] = mutated.iloc[30:] * 10.0
    after = directional_labels(mutated)
    pd.testing.assert_frame_equal(before.iloc[:10], after.iloc[:10])


def test_labels_reject_unsorted_or_non_positive_prices() -> None:
    prices = _prices(25)
    with pytest.raises(ValueError, match="sorted"):
        directional_labels(prices.iloc[::-1])
    prices.iloc[2] = 0.0
    with pytest.raises(ValueError, match="positive"):
        directional_labels(prices)


def test_tradable_targets_enter_next_open_and_count_session_closes() -> None:
    dates = pd.bdate_range("2026-01-02", periods=25)
    bars = pd.DataFrame({
        "open": np.arange(100.0, 125.0),
        "close": np.arange(101.0, 126.0),
    }, index=dates)
    labels = tradable_directional_labels(bars)
    assert labels.loc[dates[0], "entry_open"] == 100
    assert labels.loc[dates[0], "target_end_5d"] == dates[4]
    assert labels.loc[dates[0], "target_close_5d"] == 105
    assert labels.loc[dates[0], "forward_return_5d"] == pytest.approx(.05)
    assert labels["forward_return_20d"].tail(19).isna().all()
