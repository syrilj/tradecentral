"""Tests for walk-forward promotion gates and regime-aware edge helpers."""

from __future__ import annotations

import pandas as pd

try:
    from edge.research.live_edge import (
        evaluate_walk_forward_gates,
        regime_stability_score,
        select_approved_model_version,
    )
except ImportError:
    from research.live_edge import (
        evaluate_walk_forward_gates,
        regime_stability_score,
        select_approved_model_version,
    )


def test_walk_forward_insufficient_folds():
    result = evaluate_walk_forward_gates([1.0, 0.8])
    assert not result.passed
    assert any("Insufficient" in r for r in result.reasons)


def test_walk_forward_mean_sharpe_gate():
    result = evaluate_walk_forward_gates([0.4, 0.3, 0.35], min_mean_oos_sharpe=0.5)
    assert not result.passed
    assert any("Mean OOS Sharpe" in r for r in result.reasons)


def test_regime_stability_requires_multiple_regimes():
    df = pd.DataFrame(
        {
            "volatility_regime": ["HIGH", "LOW"],
            "mean_return": [0.01, 0.02],
            "n": [50, 50],
        }
    )
    score = regime_stability_score(df)
    assert score["stable"] is True
    assert score["positive_regimes"] == 2


def test_regime_stability_fails_when_concentrated():
    df = pd.DataFrame(
        {
            "volatility_regime": ["HIGH", "LOW", "MEDIUM"],
            "mean_return": [0.05, -0.01, -0.02],
            "n": [100, 40, 40],
        }
    )
    score = regime_stability_score(df)
    assert score["stable"] is False


def test_no_model_passes_gate():
    assert select_approved_model_version([{"version": "x", "fold_sharpes": [0.1]}]) is None
