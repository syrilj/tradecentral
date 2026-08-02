from __future__ import annotations

import base64
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from edge.research.artifact_predictor import load_frozen_artifact, score_frozen_artifact
from edge.research.challengers import FixedMenuXGBoostChallenger


ASOF = datetime(2026, 7, 30, 15, tzinfo=timezone.utc)


def _artifact(model: dict) -> dict:
    return {
        "schema_version": "edge-daily-directional-artifact-v1", "experiment_id": "experiment-1",
        "shadow_only": True, "broker_authorized": False, "underlying_gate": "PENDING_UNTOUCHED_HOLDOUT",
        "terminal_holdout": {"status": "SEALED_UNEVALUATED"},
        "horizons": {"10": {"horizon_days": 10, "probability_target": "underlying_directional_return_next_open_to_horizon_close",
                               "threshold": .6, "calibration": {"coefficient": 1.0, "intercept": 0.0, "version": "cal-v1"},
                               "model": model}},
    }


def _features(**values):
    return {"feature_asof": "2026-07-29T20:00:00Z", **values}


def test_scores_serialized_baselines_and_logistic_deterministically_shadow_only():
    momentum = _artifact({"type": "momentum", "score_feature": "momentum_10d"})
    first = score_frozen_artifact(momentum, _features(momentum_10d=1.0), horizon_days=10, asof_utc=ASOF)
    second = score_frozen_artifact(momentum, _features(momentum_10d=1.0), horizon_days=10, asof_utc=ASOF)
    assert first == second
    assert first["side"] == "long"
    assert first["state"] == "WATCH" and first["shadow_only"] is True
    assert first["probability_target"] == "underlying_directional_return_next_open_to_horizon_close"
    logistic = _artifact({"type": "regularized_logistic", "features": ["f1", "f2"],
                          "scaler_mean": [0, 0], "scaler_scale": [1, 2], "coefficient": [2, -1], "intercept": 0})
    result = score_frozen_artifact(logistic, _features(f1=1, f2=0), horizon_days=10, asof_utc=ASOF)
    assert result["probability"] == pytest.approx(1 / (1 + np.exp(-2)))


def test_fixed_feature_score_respects_preregistered_eligibility():
    fixed = _artifact({
        "type": "fixed_feature_score",
        "score_feature": "shock_reversal_score_5d",
        "eligibility_feature": "shock_reversal_eligible_5d",
        "fixed_probability_threshold": .5,
        "hypothesis": "volatility_normalized_one_day_shock_reversal",
    })
    eligible = score_frozen_artifact(
        fixed,
        _features(shock_reversal_score_5d=2.0, shock_reversal_eligible_5d=True),
        horizon_days=10,
        asof_utc=ASOF,
    )
    ineligible = score_frozen_artifact(
        fixed,
        _features(shock_reversal_score_5d=2.0, shock_reversal_eligible_5d=False),
        horizon_days=10,
        asof_utc=ASOF,
    )
    assert eligible["side"] == "long" and eligible["eligible"] is True
    assert ineligible["side"] == "neutral" and ineligible["eligible"] is False


def test_scores_serialized_cpu_xgboost_booster():
    index = pd.bdate_range("2025-01-02", periods=40)
    frame = pd.DataFrame({"f1": np.linspace(-1, 1, 40), "f2": np.sin(np.arange(40))}, index=index)
    labels = pd.Series(np.tile([0, 1], 20), index=index)
    fitted = FixedMenuXGBoostChallenger(feature_names=("f1", "f2")).fit(frame, labels)
    booster = bytes(fitted.estimator_.get_booster().save_raw(raw_format="json"))
    artifact = _artifact({"type": "cpu_xgboost", "features": ["f1", "f2"],
                          "booster_format": "xgboost-json-base64",
                          "booster_bytes_base64": base64.b64encode(booster).decode("ascii"), "booster_config": {}})
    result = score_frozen_artifact(artifact, _features(f1=.1, f2=.2), horizon_days=10, asof_utc=ASOF)
    assert 0 < result["probability"] < 1
    assert result["model_type"] == "cpu_xgboost"


def test_rejects_future_missing_nonfinite_and_malformed_artifacts():
    artifact = _artifact({"type": "volatility_scaled_momentum", "score_feature": "volatility_scaled_momentum_10d"})
    with pytest.raises(ValueError, match="future"):
        score_frozen_artifact(artifact, {"feature_asof": "2026-08-01T00:00:00Z", "volatility_scaled_momentum_10d": 1}, horizon_days=10, asof_utc=ASOF)
    with pytest.raises(ValueError, match="missing required"):
        score_frozen_artifact(artifact, _features(), horizon_days=10, asof_utc=ASOF)
    with pytest.raises(ValueError, match="finite"):
        score_frozen_artifact(artifact, _features(volatility_scaled_momentum_10d=float("nan")), horizon_days=10, asof_utc=ASOF)
    broken = _artifact({"type": "momentum", "score_feature": "momentum_10d"})
    broken["terminal_holdout"]["status"] = "OPENED"
    with pytest.raises(ValueError, match="sealed"):
        load_frozen_artifact(broken)
