"""Purged and embargoed time-series split primitives.

Rows are origins and a label at row ``i`` consumes observations through
``i + label_horizon`` (inclusive).  That interval is the unit protected by
purging; merely splitting origin rows is insufficient for forward labels.

Geometry — ``purged_embargoed_kfold_splits`` (k-fold; train on both sides)
---------------------------------------------------------------------------
Training rows sit on BOTH sides of the validation block, so the two boundaries
are protected by two different mechanisms:

    row index  0 ─────────────────────────────────────────────────────► n

               ┌───────────┬─────────┬──────────────┬─────────┬───────────┐
               │   train    │  purge  │  validation   │ embargo │   train    │
               └───────────┴─────────┴──────────────┴─────────┴───────────┘
               0          left      start           stop   stop+embargo    n

               left  = max(0, start - label_horizon)
               right = stop                    (purge zone is [left, stop) —
                                                 it covers the validation
                                                 block itself too, so nothing
                                                 special has to exclude it
                                                 from "train" separately)
               embargo zone = [stop, stop + embargo)

    WHY PURGE (before validation, width = label_horizon):
        A training origin ``i`` in ``[left, start)`` has a label window
        ``[i, i + label_horizon]`` that reaches into ``[start, stop)`` — part
        of its label is made from bars the validation fold is being scored
        on. Training on it leaks the validation answer into the model.

    WHY EMBARGO (after validation, width = embargo):
        Rows just after ``stop`` can still have *features* (rolling windows,
        momentum, anything backward-looking) built from bars inside the
        validation block. Training on them lets information from the
        validation period back into the model one fold early — a leak in the
        opposite direction from purge, so it needs its own zone on the other
        side.

    Both zones are cut from the training candidate set independently;
    ``train_indices`` is `candidates` with ``[left, stop)`` and
    ``[stop, stop+embargo)`` both zeroed out — never a single contiguous
    slice once a fold has training data on both sides of validation.

Geometry — ``expanding_walk_forward_splits`` (walk-forward; train precedes
validation only)
---------------------------------------------------------------------------
All training precedes validation here, so there is nothing to embargo
*after* it. ``embargo`` instead widens the same *pre*-validation gap that
``label_horizon`` already opens — both push ``train_stop`` further left,
there is only one boundary to protect:

               ┌────────────────────────────┬───────────────┬─────────────┐
               │            train             │ purge+embargo  │ validation  │
               └────────────────────────────┴───────────────┴─────────────┘
               0                       train_stop      validation_start   validation_start+validation_size

               train_stop = validation_start - label_horizon - embargo

    Same reason as above for the ``label_horizon`` component (no training
    label may reach into validation). ``embargo`` here is extra margin on
    that one boundary, not a second, post-validation zone — each fold's
    training set never resumes after its own validation block the way
    k-fold's does, so there is nothing on the far side left to protect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    train_indices: np.ndarray
    validation_indices: np.ndarray
    label_horizon: int
    embargo: int

    @property
    def train(self) -> np.ndarray:
        return self.train_indices

    @property
    def validation(self) -> np.ndarray:
        return self.validation_indices


@dataclass(frozen=True)
class NestedWalkForwardFold:
    outer: WalkForwardFold
    inner: tuple[WalkForwardFold, ...]


def _validate(n_samples: int, label_horizon: int, embargo: int) -> None:
    if n_samples < 1:
        raise ValueError("n_samples must be positive")
    if label_horizon < 1:
        raise ValueError("label_horizon must be positive")
    if embargo < 0:
        raise ValueError("embargo must be non-negative")


def expanding_walk_forward_splits(
    n_samples: int,
    *,
    label_horizon: int,
    initial_train_size: int,
    validation_size: int,
    step: int | None = None,
    embargo: int = 0,
    include_partial_final: bool = False,
    min_partial_validation_size: int = 60,
) -> Iterator[WalkForwardFold]:
    """Yield expanding historical-only folds with a pre-validation embargo gap.

    The final training origin is at least ``label_horizon`` rows before the
    first validation origin, and the optional embargo makes that gap still
    wider.  This is intentionally stricter than an ordinary expanding split.
    """
    _validate(n_samples, label_horizon, embargo)
    if initial_train_size < 1 or validation_size < 1 or min_partial_validation_size < 1:
        raise ValueError("initial_train_size and validation_size must be positive")
    if include_partial_final and min_partial_validation_size > validation_size:
        raise ValueError("min_partial_validation_size cannot exceed validation_size")
    stride = validation_size if step is None else int(step)
    if stride < 1:
        raise ValueError("step must be positive")
    fold_no = 0
    validation_start = initial_train_size + label_horizon + embargo
    while validation_start + validation_size <= n_samples:
        # The final label endpoint plus the requested embargo is strictly before
        # validation_start: i + label_horizon + embargo < validation_start.
        # See "Geometry — expanding_walk_forward_splits" in the module
        # docstring: one boundary, purge and embargo both widening the same
        # pre-validation gap (there is no post-validation training to embargo).
        train_stop = validation_start - label_horizon - embargo
        train = np.arange(0, train_stop, dtype=int)
        validation = np.arange(validation_start, validation_start + validation_size, dtype=int)
        if train.size:
            yield WalkForwardFold(fold_no, train, validation, label_horizon, embargo)
            fold_no += 1
        validation_start += stride
    remaining = n_samples - validation_start
    if include_partial_final and min_partial_validation_size <= remaining < validation_size:
        train_stop = validation_start - label_horizon - embargo
        train = np.arange(0, train_stop, dtype=int)
        validation = np.arange(validation_start, n_samples, dtype=int)
        if train.size:
            yield WalkForwardFold(fold_no, train, validation, label_horizon, embargo)


def purged_embargoed_kfold_splits(
    n_samples: int,
    *,
    label_horizon: int,
    n_splits: int = 5,
    embargo: int = 0,
) -> Iterator[WalkForwardFold]:
    """Yield contiguous-fold CV splits with label-interval purging and embargo.

    This accepts future training rows for cross-validation.  It removes every
    train origin whose label interval intersects the validation feature interval
    and removes the rows immediately after validation for the embargo.
    """
    _validate(n_samples, label_horizon, embargo)
    if not 2 <= n_splits <= n_samples:
        raise ValueError("n_splits must be between 2 and n_samples")
    for fold_no, validation in enumerate(np.array_split(np.arange(n_samples), n_splits)):
        start, stop = int(validation[0]), int(validation[-1]) + 1
        candidates = np.ones(n_samples, dtype=bool)
        # [i, i+h] intersects [start, stop-1] iff i <= stop-1 and i+h >= start.
        # See "Geometry — purged_embargoed_kfold_splits" in the module
        # docstring: [left, stop) is the purge zone (also swallows the
        # validation block itself), [stop, stop+embargo) is the embargo zone.
        left = max(0, start - label_horizon)
        right = min(n_samples, stop)
        candidates[left:right] = False
        candidates[stop:min(n_samples, stop + embargo)] = False
        yield WalkForwardFold(
            fold_no,
            np.flatnonzero(candidates),
            validation,
            label_horizon,
            embargo,
        )


def nested_walk_forward_splits(
    n_samples: int,
    *,
    label_horizon: int,
    outer_initial_train_size: int,
    outer_validation_size: int,
    inner_initial_train_size: int,
    inner_validation_size: int,
    outer_step: int | None = None,
    inner_step: int | None = None,
    embargo: int = 0,
    include_partial_final_outer: bool = False,
    min_partial_outer_validation_size: int = 60,
) -> Iterator[NestedWalkForwardFold]:
    """Yield outer evaluation folds and historical-only inner selection folds.

    The inner folds are expressed in global row coordinates so callers cannot
    accidentally index a full feature matrix using relative coordinates.
    """
    for outer in expanding_walk_forward_splits(
        n_samples,
        label_horizon=label_horizon,
        initial_train_size=outer_initial_train_size,
        validation_size=outer_validation_size,
        step=outer_step,
        embargo=embargo,
        include_partial_final=include_partial_final_outer,
        min_partial_validation_size=min_partial_outer_validation_size,
    ):
        available = int(outer.train_indices.size)
        inner: list[WalkForwardFold] = []
        for local in expanding_walk_forward_splits(
            available,
            label_horizon=label_horizon,
            initial_train_size=inner_initial_train_size,
            validation_size=inner_validation_size,
            step=inner_step,
            embargo=embargo,
            include_partial_final=False,
        ):
            inner.append(
                WalkForwardFold(
                    local.fold,
                    outer.train_indices[local.train_indices],
                    outer.train_indices[local.validation_indices],
                    label_horizon,
                    embargo,
                )
            )
        yield NestedWalkForwardFold(outer=outer, inner=tuple(inner))
