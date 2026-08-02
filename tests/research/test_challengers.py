from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research import challengers
from edge.research.challengers import FixedMenuXGBoostChallenger, XGBOOST_CPU_MENU


FEATURES = ("f1", "f2", "f3")


def _data(n: int = 160) -> tuple[pd.DataFrame, pd.Series]:
    x = np.linspace(-2.0, 2.0, n)
    frame = pd.DataFrame({"f1": x, "f2": np.sin(x), "f3": x ** 2},
                         index=pd.bdate_range("2025-01-02", periods=n))
    labels = pd.Series((x + .2 * np.sin(x) > 0).astype(int), index=frame.index)
    return frame, labels


def test_fixed_menu_is_cpu_only_and_challenger_uses_supplied_train_rows_only():
    config = XGBOOST_CPU_MENU["conservative_v1"]
    assert config["device"] == "cpu"
    assert config["tree_method"] == "hist"
    assert config["n_jobs"] == 1
    with pytest.raises(TypeError):
        config["device"] = "cuda"

    features, labels = _data()
    model = FixedMenuXGBoostChallenger(feature_names=FEATURES).fit(features.iloc[:100], labels.iloc[:100])
    assert model.fitted_row_count_ == 100
    assert tuple(model.estimator_.feature_names_in_) == FEATURES


def test_future_or_test_row_mutation_cannot_change_prediction_for_unchanged_row():
    features, labels = _data()
    model = FixedMenuXGBoostChallenger(feature_names=FEATURES).fit(features.iloc[:100], labels.iloc[:100])
    original = model.predict_proba(features.iloc[100:])
    mutated = features.iloc[100:].copy()
    mutated.iloc[1:, :] *= 10_000
    after = model.predict_proba(mutated)
    assert original.iloc[0] == pytest.approx(after.iloc[0])


def test_challenger_refuses_single_class_or_unavailable_dependency(monkeypatch):
    features, labels = _data()
    with pytest.raises(ValueError, match="both direction classes"):
        FixedMenuXGBoostChallenger(feature_names=FEATURES).fit(features.iloc[:20], pd.Series(0, index=features.index[:20]))
    monkeypatch.setattr(challengers, "_load_xgboost", lambda: (_ for _ in ()).throw(RuntimeError("xgboost is unavailable")))
    with pytest.raises(RuntimeError, match="unavailable"):
        FixedMenuXGBoostChallenger(feature_names=FEATURES).fit(features.iloc[:100], labels.iloc[:100])
