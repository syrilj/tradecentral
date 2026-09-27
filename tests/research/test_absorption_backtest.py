"""Tests for the absorption reversal backtest (research/absorption_backtest.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.daily_plays.absorption import (
    AbsorptionConfig,
    detect_absorption_series,
    observations_from_bars,
)
from edge.research.absorption_backtest import (
    _pr_auc,
    _roc_auc,
    backtest_absorption,
    label_reversals,
)


def _bars(closes, volumes, opens=None):
    n = len(closes)
    opens = opens if opens is not None else closes
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": opens,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=idx,
    )


def _absorbed_selling_then_reversal():
    n = 120
    closes = [100.0] * n
    closes[-20:] = [99.85] * 20  # absorbed selling (close near low)
    closes[-5:] = [101.0] * 5  # reversal up
    volumes = [1000.0] * n
    volumes[-20:] = [5000.0] * 20
    return _bars(closes, volumes)


def test_label_reversals_is_causal_and_skips_truncated_signals():
    bars = _absorbed_selling_then_reversal()
    observations = observations_from_bars(bars)
    readouts = detect_absorption_series(observations)
    prices = [float(c) for c in bars["close"]]
    labels = label_reversals(readouts, prices, horizon=5, threshold=0.005)
    # Every label must have a full horizon of future bars.
    assert all(label.index + 5 < len(prices) for label in labels)
    # A sell-absorption signal expects a reversal up (direction +1).
    assert all(label.direction == 1 for label in labels)


def test_backtest_reports_every_pinned_key():
    bars = _absorbed_selling_then_reversal()
    result = backtest_absorption(bars, horizon=5, threshold=0.005)
    for key in (
        "symbol", "n_bars", "n_signals", "n_hits", "precision", "recall", "f1",
        "roc_auc", "pr_auc", "win_rate", "expectancy", "sharpe", "max_drawdown",
        "profit_factor", "horizon", "threshold", "labels", "caveats",
    ):
        assert key in result
    assert result["recall"] is None
    assert result["f1"] is None
    assert result["n_signals"] == result["n_hits"] + (result["n_signals"] - result["n_hits"])


def test_backtest_no_signals_is_not_an_error():
    flat = _bars([100.0] * 60, [1000.0] * 60)
    result = backtest_absorption(flat)
    assert result["n_signals"] == 0
    assert result["precision"] is None
    assert result["labels"] == []


def test_roc_auc_undefined_without_both_classes():
    assert np.isnan(_roc_auc(np.array([True, True]), np.array([0.5, 0.6])))
    assert np.isnan(_roc_auc(np.array([False, False]), np.array([0.5, 0.6])))


def test_roc_auc_perfect_separation_is_one():
    y = np.array([False, False, True, True])
    scores = np.array([0.1, 0.2, 0.9, 1.0])
    assert _roc_auc(y, scores) == pytest.approx(1.0)


def test_pr_auc_perfect_separation_is_one():
    y = np.array([False, False, True, True])
    scores = np.array([0.1, 0.2, 0.9, 1.0])
    assert _pr_auc(y, scores) == pytest.approx(1.0)


def test_pr_auc_undefined_without_positives():
    assert np.isnan(_pr_auc(np.array([False, False]), np.array([0.1, 0.2])))
