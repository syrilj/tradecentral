"""Preregistered CPU-only XGBoost challengers for offline research comparisons."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .features import feature_columns


# This is a deliberately small, immutable menu rather than a tuning surface.
# Any additional configuration is a separate preregistered experiment.
XGBOOST_CPU_MENU: Mapping[str, Mapping[str, Any]] = MappingProxyType({
    "conservative_v1": MappingProxyType({
        "n_estimators": 120,
        "max_depth": 2,
        "learning_rate": 0.03,
        "min_child_weight": 10,
        "subsample": 0.80,
        "colsample_bytree": 0.80,
        "reg_alpha": 0.10,
        "reg_lambda": 5.0,
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "tree_method": "hist",
        "device": "cpu",
        "n_jobs": 1,
        "random_state": 0,
        "verbosity": 0,
    }),
})


def _load_xgboost() -> Any:
    """Import lazily so missing optional research dependencies fail closed."""
    try:
        return import_module("xgboost")
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("xgboost is unavailable; CPU challenger cannot run") from exc


@dataclass
class FixedMenuXGBoostChallenger:
    """Deterministic CPU binary challenger fit exclusively on supplied rows.

    It returns raw classifier probabilities only; calibration and all model
    selection must happen inside the caller's nested training folds.
    """

    menu_name: str = "conservative_v1"
    feature_names: tuple[str, ...] = field(default_factory=feature_columns)
    estimator_: Any | None = field(default=None, init=False)
    fitted_row_count_: int = field(default=0, init=False)

    @property
    def config(self) -> Mapping[str, Any]:
        try:
            return XGBOOST_CPU_MENU[self.menu_name]
        except KeyError as exc:
            raise ValueError(f"unknown preregistered XGBoost menu item: {self.menu_name}") from exc

    def _matrix(self, features: pd.DataFrame) -> pd.DataFrame:
        missing = [name for name in self.feature_names if name not in features]
        if missing:
            raise KeyError(f"features missing explicit challenger columns: {', '.join(missing)}")
        return features.loc[:, self.feature_names].apply(pd.to_numeric, errors="coerce")

    def fit(self, train_features: pd.DataFrame, train_labels: pd.Series | np.ndarray) -> "FixedMenuXGBoostChallenger":
        """Fit on training rows supplied by the caller, with no validation set.

        In particular, no holdout/test input is accepted or inspected here.
        Rows with missing/non-finite values are excluded rather than imputed
        using a statistic that could accidentally be fit on a broader panel.
        """
        matrix = self._matrix(train_features)
        labels = pd.Series(train_labels, index=train_features.index, dtype="float64")
        valid = np.isfinite(matrix).all(axis=1) & labels.isin((0.0, 1.0))
        if not valid.any():
            raise ValueError("no finite challenger training rows")
        y = labels.loc[valid].astype(int)
        if y.nunique() != 2:
            raise ValueError("XGBoost challenger requires both direction classes in training rows")
        config = dict(self.config)
        if config.get("device") != "cpu" or config.get("tree_method") != "hist" or config.get("n_jobs") != 1:
            raise ValueError("challenger configuration must remain deterministic CPU hist with one worker")
        xgboost = _load_xgboost()
        self.estimator_ = xgboost.XGBClassifier(**config)
        self.estimator_.fit(matrix.loc[valid], y)
        self.fitted_row_count_ = int(valid.sum())
        return self

    def predict_proba(self, features: pd.DataFrame) -> pd.Series:
        """Return raw positive-class probabilities for finite supplied rows."""
        if self.estimator_ is None:
            raise RuntimeError("fit must be called before predict_proba")
        matrix = self._matrix(features)
        valid = np.isfinite(matrix).all(axis=1)
        result = pd.Series(np.nan, index=features.index, name="raw_xgboost_probability")
        if valid.any():
            result.loc[valid] = self.estimator_.predict_proba(matrix.loc[valid])[:, 1]
        return result

    def predict_direction(self, features: pd.DataFrame) -> pd.Series:
        probability = self.predict_proba(features)
        return pd.Series(np.where(probability.notna(), (probability >= .5).astype(int), np.nan),
                         index=probability.index, name="xgboost_direction")
