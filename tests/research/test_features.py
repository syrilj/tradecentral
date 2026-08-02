"""Tests for the feature-degeneracy assertion.

The systemic control behind the `short_pressure` incident
(edge/docs/LOOKAHEAD_CORRECTION.md): a feature column that silently
collapses to a constant, or arrives all-null, must fail the run instead of
degrading quietly while a downstream result document keeps describing it as
active. `load_finra_short_vol()` raising (see test_data_sources.py) closes
that one incident; this assertion closes the class.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.features import assert_no_degenerate_feature_columns, causal_daily_features


def test_constant_column_raises_naming_the_column() -> None:
    df = pd.DataFrame({"ok": np.arange(10.0), "bad": [0.5] * 10})
    with pytest.raises(ValueError, match="'bad'"):
        assert_no_degenerate_feature_columns(df)


def test_all_null_column_raises_naming_the_column() -> None:
    df = pd.DataFrame({"ok": np.arange(10.0), "bad": [np.nan] * 10})
    with pytest.raises(ValueError, match="'bad'"):
        assert_no_degenerate_feature_columns(df)


def test_normal_varying_columns_pass() -> None:
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"a": rng.normal(size=50), "b": np.arange(50.0)})
    assert_no_degenerate_feature_columns(df)  # must not raise


def test_binary_zero_one_feature_is_not_degenerate() -> None:
    """Two distinct values is real variance, however small the alphabet."""
    df = pd.DataFrame({"ok": np.arange(20.0), "flag": np.tile([0.0, 1.0], 10)})
    assert_no_degenerate_feature_columns(df)  # must not raise


def test_single_row_frame_does_not_false_positive() -> None:
    """With one row, 'the only value' is trivially 'the only distinct value'
    — that is not evidence of a degenerate feature, just of a 1-row frame."""
    df = pd.DataFrame({"a": [1.0], "b": [np.nan]})
    assert_no_degenerate_feature_columns(df)  # must not raise


def test_two_row_frame_does_not_false_positive() -> None:
    """Two matching values could be an honest coincidence at this sample
    size; not enough evidence to fail a run over."""
    df = pd.DataFrame({"a": [1.0, 1.0], "b": [np.nan, np.nan]})
    assert_no_degenerate_feature_columns(df)  # must not raise


def test_three_row_identical_values_do_raise() -> None:
    """The row-count guard is only for 1-2 row frames; once there are enough
    rows to mean something, a real constant still fails."""
    df = pd.DataFrame({"bad": [2.0, 2.0, 2.0]})
    with pytest.raises(ValueError, match="'bad'"):
        assert_no_degenerate_feature_columns(df)


def test_mostly_null_with_one_repeated_value_is_still_degenerate() -> None:
    """Zero variance among the non-null values counts even when most rows
    are null — a rolling-window column that, once warmed up, never actually
    moves is exactly as uninformative as one that is constant from row 0."""
    df = pd.DataFrame({"bad": [np.nan, np.nan, np.nan, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]})
    with pytest.raises(ValueError, match="'bad'"):
        assert_no_degenerate_feature_columns(df)


def test_wired_into_causal_daily_features_pipeline() -> None:
    """causal_daily_features calls the assertion itself; a legitimate,
    varying panel must run to completion unchanged."""
    n = 80
    index = pd.bdate_range("2024-01-02", periods=n)
    rows = []
    for symbol, phase in (("AAA", 0.0), ("BBB", 0.7)):
        close = 100 + np.arange(n) * 0.1 + np.sin(np.arange(n) / 4 + phase)
        # A pure arithmetic ramp makes volume_z_20d exactly constant under a
        # fixed rolling window -- itself a real, if inadvertent, degenerate
        # column. Wiggle it the same way `close` is wiggled above.
        volume = 1_000 + np.arange(n) + 5 * np.sin(np.arange(n) / 4 + phase)
        frame = pd.DataFrame({
            "open": close, "high": close + 1, "low": close - 1, "close": close,
            "volume": volume,
        }, index=index)
        frame["symbol"] = symbol
        rows.append(frame.reset_index(names="timestamp").set_index(["timestamp", "symbol"]))
    bars = pd.concat(rows).sort_index()

    features = causal_daily_features(bars)

    assert len(features) == 2 * n


def test_causal_daily_features_surfaces_a_degenerate_input_column() -> None:
    """If every symbol's price is dead flat, close_to_sma_20d and every
    momentum column collapse to a constant 0.0 once warmed up — the pipeline
    must refuse to hand that panel to a model instead of silently scoring it."""
    n = 80
    index = pd.bdate_range("2024-01-02", periods=n)
    flat = np.full(n, 100.0)
    frame = pd.DataFrame({
        "open": flat, "high": flat + 1, "low": flat - 1, "close": flat,
        "volume": np.full(n, 1_000.0),
    }, index=index)
    frame["symbol"] = "FLAT"
    bars = frame.reset_index(names="timestamp").set_index(["timestamp", "symbol"])

    with pytest.raises(ValueError, match="constant"):
        causal_daily_features(bars)
