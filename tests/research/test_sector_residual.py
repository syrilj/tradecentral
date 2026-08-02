from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.sector_residual import sector_residual_momentum_20d


def _panel() -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-02"] * 4 + ["2024-01-03"] * 4),
        "symbol": ["A", "B", "C", "D"] * 2,
        "sector": ["tech", "tech", "tech", "solo"] * 2,
        "momentum_20d": [0.10, 0.20, 0.40, 0.30, 0.15, 0.25, 0.35, 0.20],
        "realized_volatility_20d": [0.10] * 8,
    })


def test_leave_one_out_peer_mean_excludes_own_momentum_and_keeps_singletons() -> None:
    result = sector_residual_momentum_20d(_panel())
    first = result[result["timestamp"] == pd.Timestamp("2024-01-02")].set_index("symbol")
    assert first.loc["A", "sector_residual_peer_count_20d"] == 2
    assert first.loc["A", "sector_residual_20d"] == pytest.approx(-0.20)  # 0.10 - mean(0.20, 0.40)
    assert first.loc["B", "sector_residual_20d"] == pytest.approx(-0.05)  # 0.20 - mean(0.10, 0.40)
    assert first.loc["C", "sector_residual_20d"] == pytest.approx(0.25)   # 0.40 - mean(0.10, 0.20)
    assert first.loc["D", "sector_residual_peer_count_20d"] == 0
    assert first.loc["D", "sector_residual_score_20d"] == 0.0
    assert not first.loc["D", "sector_residual_available_20d"]
    assert not first.loc["D", "sector_residual_eligible_20d"]


def test_tied_scores_share_deterministic_percentiles_and_edge_eligibility() -> None:
    panel = pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-02"] * 4),
        "symbol": ["A", "B", "C", "D"],
    # Two sector pairs create two tied low and two tied high residual scores.
        "sector": ["low", "low", "high", "high"],
        "momentum_20d": [0.10, 0.20, 0.40, 0.30],
        "realized_volatility_20d": [0.10] * 4,
    })
    result = sector_residual_momentum_20d(panel).set_index("symbol")
    assert result.loc["A", "sector_residual_score_percentile_20d"] == pytest.approx(1 / 6)
    assert result.loc["D", "sector_residual_score_percentile_20d"] == pytest.approx(1 / 6)
    assert result.loc["B", "sector_residual_score_percentile_20d"] == pytest.approx(5 / 6)
    assert result.loc["C", "sector_residual_score_percentile_20d"] == pytest.approx(5 / 6)
    assert result["sector_residual_eligible_20d"].all()


def test_future_date_mutation_cannot_change_prior_date_signal() -> None:
    panel = _panel()
    before = sector_residual_momentum_20d(panel)
    changed = panel.copy()
    changed.loc[changed["timestamp"] == pd.Timestamp("2024-01-03"), "momentum_20d"] = np.array([10.0, -10.0, 20.0, -20.0])
    after = sector_residual_momentum_20d(changed)
    columns = [
        "sector_residual_peer_count_20d", "sector_residual_available_20d", "sector_residual_20d",
        "sector_residual_score_20d", "sector_residual_score_percentile_20d", "sector_residual_eligible_20d",
    ]
    pd.testing.assert_frame_equal(
        before.loc[before["timestamp"] == pd.Timestamp("2024-01-02"), columns].reset_index(drop=True),
        after.loc[after["timestamp"] == pd.Timestamp("2024-01-02"), columns].reset_index(drop=True),
    )


def test_unavailable_neutral_singleton_does_not_shift_available_percentile_cutoffs() -> None:
    panel = pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-02"] * 5),
        "symbol": ["A", "B", "C", "D", "S"],
        # Available scores are [-2, -1, +1, +2]; S is a neutral singleton.
        "sector": ["left", "left", "right", "right", "solo"],
        "momentum_20d": [0.10, 0.20, 0.10, 0.20, 0.50],
        "realized_volatility_20d": [0.05, 0.10, 0.10, 0.05, 0.10],
    })
    result = sector_residual_momentum_20d(panel).set_index("symbol")
    assert result.loc["S", "sector_residual_score_percentile_20d"] == 0.5
    assert not result.loc["S", "sector_residual_eligible_20d"]
    # Four available scores mean ranks 2 and 3 are 1/3 and 2/3: neither is an edge.
    assert result.loc["C", "sector_residual_score_percentile_20d"] == pytest.approx(1 / 3)
    assert result.loc["B", "sector_residual_score_percentile_20d"] == pytest.approx(2 / 3)
    assert not result.loc["B", "sector_residual_eligible_20d"]
    assert not result.loc["C", "sector_residual_eligible_20d"]
