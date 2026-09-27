from __future__ import annotations

import numpy as np
import pandas as pd

from edge.research.panel_splits import (
    expanding_panel_walk_forward_splits,
    nested_panel_walk_forward_splits,
    split_development_and_holdout,
)


def _panel(n_dates: int = 80) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=n_dates)
    index = pd.MultiIndex.from_product([dates, ["AAA", "BBB", "CCC"]],
                                       names=["timestamp", "symbol"])
    frame = pd.DataFrame({"value": np.arange(len(index))}, index=index)
    frame["target_end_5d"] = np.repeat(pd.Series(dates).shift(-5).to_numpy(), 3)
    return frame


def test_panel_split_keeps_dates_together_and_purges_label_intervals():
    panel = _panel()
    folds = list(expanding_panel_walk_forward_splits(
        panel, label_horizon=5, initial_train_dates=30,
        validation_dates=10, embargo_dates=3,
    ))
    assert folds
    for fold in folds:
        assert len(fold.train_indices) % 3 == len(fold.validation_indices) % 3 == 0
        assert set(panel.iloc[fold.train_indices].index.get_level_values("symbol")) == {"AAA", "BBB", "CCC"}
        assert fold.train_dates[-1] < fold.validation_dates[0]
        unique_dates = panel.index.get_level_values("timestamp").unique()
        train_last = unique_dates.get_loc(fold.train_dates[-1])
        validation_first = unique_dates.get_loc(fold.validation_dates[0])
        assert train_last + fold.label_horizon + fold.embargo < validation_first


def test_nested_panel_inner_rows_are_strictly_inside_outer_training_rows():
    panel = _panel(120)
    folds = list(nested_panel_walk_forward_splits(
        panel, label_horizon=5,
        outer_initial_train_dates=50, outer_validation_dates=15,
        inner_initial_train_dates=20, inner_validation_dates=10,
        embargo_dates=2,
    ))
    assert folds and folds[0].inner
    for nested in folds:
        outer_train = set(nested.outer.train_indices)
        for inner in nested.inner:
            assert set(inner.train_indices).issubset(outer_train)
            assert set(inner.validation_indices).issubset(outer_train)
            assert set(inner.train_indices).isdisjoint(inner.validation_indices)


def test_terminal_holdout_excludes_development_labels_crossing_boundary():
    panel = _panel(30)
    start = panel.index.get_level_values("timestamp").unique()[20]
    development, holdout = split_development_and_holdout(
        panel, holdout_start=start, target_end_column="target_end_5d",
    )
    assert development.index.get_level_values("timestamp").max() < start
    assert pd.to_datetime(development["target_end_5d"]).max() < start
    assert holdout.index.get_level_values("timestamp").min() == start


def test_panel_partial_final_fold_keeps_all_symbols_on_latest_dates():
    panel = _panel(100)
    folds = list(expanding_panel_walk_forward_splits(
        panel, label_horizon=5, initial_train_dates=20, validation_dates=30,
        step_dates=30, embargo_dates=2, include_partial_final=True,
        min_partial_validation_dates=10,
    ))
    final = folds[-1]
    assert len(final.validation_dates) == 13
    assert final.validation_dates[-1] == panel.index.get_level_values("timestamp").unique()[-1]
    rows = panel.iloc[final.validation_indices]
    assert set(rows.index.get_level_values("timestamp")) == set(final.validation_dates)
    assert rows.groupby(level="timestamp").size().eq(3).all()
