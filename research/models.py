"""Frozen simple baselines for daily directional research (no GPU/boosting)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from .features import feature_columns
from .labels import FROZEN_HORIZONS


def baseline_scores(features: pd.DataFrame, *, horizon_days: int) -> pd.DataFrame:
    """Return ordinal momentum baselines, explicitly not calibrated odds."""
    horizon = int(horizon_days)
    if horizon not in FROZEN_HORIZONS:
        raise ValueError(f"horizon_days must be one of {FROZEN_HORIZONS}")
    momentum_key = f"momentum_{horizon}d"
    scaled_key = f"volatility_scaled_momentum_{horizon}d"
    missing = [column for column in (momentum_key, scaled_key) if column not in features]
    if missing:
        raise KeyError(f"features missing baseline columns: {', '.join(missing)}")
    result = pd.DataFrame(index=features.index)
    result["momentum_score"] = pd.to_numeric(features[momentum_key], errors="coerce")
    result["volatility_scaled_momentum_score"] = pd.to_numeric(features[scaled_key], errors="coerce")
    result["momentum_direction"] = np.sign(result["momentum_score"]).astype("float")
    result["volatility_scaled_momentum_direction"] = np.sign(result["volatility_scaled_momentum_score"]).astype("float")
    return result


@dataclass
class RegularizedLogisticBaseline:
    """Fixed L2 logistic baseline whose scaler is fit on supplied train rows only."""

    C: float = 1.0
    max_iter: int = 1_000
    random_state: int = 0
    feature_names: tuple[str, ...] = field(default_factory=feature_columns)
    scaler_: StandardScaler | None = field(default=None, init=False)
    estimator_: LogisticRegression | None = field(default=None, init=False)

    def _matrix(self, features: pd.DataFrame) -> pd.DataFrame:
        missing = [column for column in self.feature_names if column not in features]
        if missing:
            raise KeyError(f"features missing frozen columns: {', '.join(missing)}")
        return features.loc[:, self.feature_names].apply(pd.to_numeric, errors="coerce")

    def fit(self, train_features: pd.DataFrame, train_labels: pd.Series | np.ndarray) -> "RegularizedLogisticBaseline":
        """Fit preprocessing and classifier solely on caller-supplied train rows."""
        if self.C <= 0 or self.max_iter < 1:
            raise ValueError("C and max_iter must be positive")
        matrix = self._matrix(train_features)
        target = pd.Series(train_labels, index=train_features.index, dtype="float64")
        valid = matrix.notna().all(axis=1) & target.isin((0.0, 1.0))
        if not valid.any():
            raise ValueError("no finite training rows")
        y = target.loc[valid].astype(int)
        if y.nunique() != 2:
            raise ValueError("logistic baseline requires both direction classes in training rows")
        scaler = StandardScaler().fit(matrix.loc[valid])
        estimator = LogisticRegression(C=self.C, solver="lbfgs", max_iter=self.max_iter,
                                       random_state=self.random_state).fit(scaler.transform(matrix.loc[valid]), y)
        self.scaler_, self.estimator_ = scaler, estimator
        return self

    def predict_proba(self, features: pd.DataFrame) -> pd.Series:
        """Return raw logistic probabilities; calibration is a separate research step."""
        if self.scaler_ is None or self.estimator_ is None:
            raise RuntimeError("fit must be called before predict_proba")
        matrix = self._matrix(features)
        valid = matrix.notna().all(axis=1)
        result = pd.Series(np.nan, index=features.index, name="raw_logistic_probability")
        if valid.any():
            result.loc[valid] = self.estimator_.predict_proba(self.scaler_.transform(matrix.loc[valid]))[:, 1]
        return result

    def predict_direction(self, features: pd.DataFrame) -> pd.Series:
        probability = self.predict_proba(features)
        return pd.Series(np.where(probability.notna(), (probability >= .5).astype(int), np.nan), index=probability.index,
                         name="logistic_direction")
