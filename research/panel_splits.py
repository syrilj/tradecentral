"""Trading-date splits for cross-sectional daily research panels.

All symbols observed on one market date stay in the same fold.  Purging and
embargo are applied to the unique trading-date axis, never to arbitrary panel
row positions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd

from .splits import WalkForwardFold, expanding_walk_forward_splits


@dataclass(frozen=True)
class PanelWalkForwardFold:
    fold: int
    train_dates: pd.DatetimeIndex
    validation_dates: pd.DatetimeIndex
    train_indices: np.ndarray
    validation_indices: np.ndarray
    label_horizon: int
    embargo: int


@dataclass(frozen=True)
class NestedPanelWalkForwardFold:
    outer: PanelWalkForwardFold
    inner: tuple[PanelWalkForwardFold, ...]


def trading_dates(records: pd.DataFrame, *, date_level: str = "timestamp") -> pd.DatetimeIndex:
    """Return the sorted, unique, timezone-naive trading dates in a panel."""
    if isinstance(records.index, pd.MultiIndex) and date_level in records.index.names:
        raw = records.index.get_level_values(date_level)
    elif isinstance(records.index, pd.DatetimeIndex) and records.index.name == date_level:
        raw = records.index
    elif date_level in records:
        raw = records[date_level]
    else:
        raise KeyError(f"records have no trading-date field: {date_level}")
    dates = pd.DatetimeIndex(pd.to_datetime(raw, errors="coerce"))
    if dates.isna().any():
        raise ValueError("trading dates must be valid")
    if dates.tz is not None:
        dates = dates.tz_convert("UTC").tz_localize(None)
    return pd.DatetimeIndex(dates.normalize().unique()).sort_values()


def _row_dates(records: pd.DataFrame, *, date_level: str) -> pd.DatetimeIndex:
    if isinstance(records.index, pd.MultiIndex) and date_level in records.index.names:
        raw = records.index.get_level_values(date_level)
    elif isinstance(records.index, pd.DatetimeIndex) and records.index.name == date_level:
        raw = records.index
    else:
        raw = records[date_level]
    dates = pd.DatetimeIndex(pd.to_datetime(raw, errors="raise"))
    if dates.tz is not None:
        dates = dates.tz_convert("UTC").tz_localize(None)
    return dates.normalize()


def _map_fold(records: pd.DataFrame, dates: pd.DatetimeIndex, fold: WalkForwardFold,
              *, date_level: str) -> PanelWalkForwardFold:
    train_dates = dates[fold.train_indices]
    validation_dates = dates[fold.validation_indices]
    rows = _row_dates(records, date_level=date_level)
    return PanelWalkForwardFold(
        fold=fold.fold,
        train_dates=train_dates,
        validation_dates=validation_dates,
        train_indices=np.flatnonzero(rows.isin(train_dates)),
        validation_indices=np.flatnonzero(rows.isin(validation_dates)),
        label_horizon=fold.label_horizon,
        embargo=fold.embargo,
    )


def expanding_panel_walk_forward_splits(
    records: pd.DataFrame,
    *,
    label_horizon: int,
    initial_train_dates: int,
    validation_dates: int,
    step_dates: int | None = None,
    embargo_dates: int = 0,
    include_partial_final: bool = False,
    min_partial_validation_dates: int = 60,
    date_level: str = "timestamp",
) -> Iterator[PanelWalkForwardFold]:
    """Yield historical-only folds while keeping each date's symbols together."""
    dates = trading_dates(records, date_level=date_level)
    for fold in expanding_walk_forward_splits(
        len(dates),
        label_horizon=label_horizon,
        initial_train_size=initial_train_dates,
        validation_size=validation_dates,
        step=step_dates,
        embargo=embargo_dates,
        include_partial_final=include_partial_final,
        min_partial_validation_size=min_partial_validation_dates,
    ):
        yield _map_fold(records, dates, fold, date_level=date_level)


def nested_panel_walk_forward_splits(
    records: pd.DataFrame,
    *,
    label_horizon: int,
    outer_initial_train_dates: int,
    outer_validation_dates: int,
    inner_initial_train_dates: int,
    inner_validation_dates: int,
    outer_step_dates: int | None = None,
    inner_step_dates: int | None = None,
    embargo_dates: int = 0,
    include_partial_final_outer: bool = False,
    min_partial_outer_validation_dates: int = 60,
    date_level: str = "timestamp",
) -> Iterator[NestedPanelWalkForwardFold]:
    """Yield nested historical folds in global panel-row coordinates."""
    for outer in expanding_panel_walk_forward_splits(
        records,
        label_horizon=label_horizon,
        initial_train_dates=outer_initial_train_dates,
        validation_dates=outer_validation_dates,
        step_dates=outer_step_dates,
        embargo_dates=embargo_dates,
        include_partial_final=include_partial_final_outer,
        min_partial_validation_dates=min_partial_outer_validation_dates,
        date_level=date_level,
    ):
        outer_train = records.iloc[outer.train_indices]
        inner = tuple(
            PanelWalkForwardFold(
                fold=fold.fold,
                train_dates=fold.train_dates,
                validation_dates=fold.validation_dates,
                train_indices=outer.train_indices[fold.train_indices],
                validation_indices=outer.train_indices[fold.validation_indices],
                label_horizon=fold.label_horizon,
                embargo=fold.embargo,
            )
            for fold in expanding_panel_walk_forward_splits(
                outer_train,
                label_horizon=label_horizon,
                initial_train_dates=inner_initial_train_dates,
                validation_dates=inner_validation_dates,
                step_dates=inner_step_dates,
                embargo_dates=embargo_dates,
                include_partial_final=False,
                date_level=date_level,
            )
        )
        yield NestedPanelWalkForwardFold(outer=outer, inner=inner)


def split_development_and_holdout(
    records: pd.DataFrame,
    *,
    holdout_start: object,
    target_end_column: str,
    date_level: str = "timestamp",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Seal a terminal holdout and exclude labels crossing its boundary."""
    if target_end_column not in records:
        raise KeyError(f"missing target end column: {target_end_column}")
    start = pd.Timestamp(holdout_start).normalize()
    dates = _row_dates(records, date_level=date_level)
    target_end = pd.to_datetime(records[target_end_column], errors="coerce")
    if getattr(target_end.dt, "tz", None) is not None:
        target_end = target_end.dt.tz_convert("UTC").dt.tz_localize(None)
    development_mask = (dates < start) & target_end.notna() & (target_end.dt.normalize() < start)
    holdout_mask = dates >= start
    return records.loc[development_mask].copy(), records.loc[holdout_mask].copy()
