from __future__ import annotations

import numpy as np

from edge.research.splits import (
    expanding_walk_forward_splits,
    nested_walk_forward_splits,
    purged_embargoed_kfold_splits,
)


def _assert_no_label_overlap(train: np.ndarray, validation: np.ndarray, horizon: int) -> None:
    first, last = int(validation.min()), int(validation.max())
    assert all(index + horizon < first or index > last for index in train)


def test_expanding_walk_forward_purges_labels_and_embargoes_boundary() -> None:
    folds = list(
        expanding_walk_forward_splits(
            80,
            label_horizon=5,
            initial_train_size=20,
            validation_size=10,
            step=10,
            embargo=3,
        )
    )
    assert len(folds) >= 3
    for fold in folds:
        assert fold.train.max() + fold.label_horizon < fold.validation.min()
        assert fold.validation.min() - (fold.train.max() + fold.label_horizon) - 1 == fold.embargo
        _assert_no_label_overlap(fold.train, fold.validation, fold.label_horizon)
        assert np.all(np.diff(fold.train) == 1)


def test_kfold_removes_label_overlap_and_post_validation_embargo() -> None:
    horizon, embargo = 4, 3
    folds = list(purged_embargoed_kfold_splits(50, label_horizon=horizon, n_splits=5, embargo=embargo))
    assert len(folds) == 5
    for fold in folds:
        _assert_no_label_overlap(fold.train, fold.validation, horizon)
        stop = int(fold.validation.max()) + 1
        assert not set(range(stop, min(50, stop + embargo))).intersection(fold.train)


def test_nested_inner_indices_are_global_and_stay_inside_outer_train() -> None:
    nested = list(
        nested_walk_forward_splits(
            120,
            label_horizon=5,
            outer_initial_train_size=45,
            outer_validation_size=10,
            inner_initial_train_size=20,
            inner_validation_size=5,
            embargo=2,
        )
    )
    assert nested and all(item.inner for item in nested)
    for item in nested:
        outer_train = set(item.outer.train)
        for inner in item.inner:
            assert set(inner.train).issubset(outer_train)
            assert set(inner.validation).issubset(outer_train)
            _assert_no_label_overlap(inner.train, inner.validation, 5)
            assert inner.validation.min() - (inner.train.max() + inner.label_horizon) - 1 == inner.embargo


def test_opt_in_partial_final_fold_reaches_latest_rows_without_changing_purge():
    kwargs = dict(n_samples=100, label_horizon=5, initial_train_size=20,
                  validation_size=30, step=30, embargo=2)
    default = list(expanding_walk_forward_splits(**kwargs))
    partial = list(expanding_walk_forward_splits(
        **kwargs, include_partial_final=True, min_partial_validation_size=10,
    ))
    assert len(partial) == len(default) + 1
    final = partial[-1]
    assert final.validation.tolist() == list(range(87, 100))
    assert final.train.max() + final.label_horizon + final.embargo < final.validation.min()
    assert final.fold == default[-1].fold + 1
