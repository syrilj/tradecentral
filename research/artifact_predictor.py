"""Fail-closed scoring of frozen daily directional research artifacts.

This module is intentionally offline: it reads only a supplied artifact and
caller-supplied, point-in-time features.  It does not load market data, read a
terminal holdout, select options, or place orders.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


SCHEMA_VERSION = "edge-daily-directional-artifact-v1"
_MODEL_TYPES = frozenset({
    "momentum",
    "volatility_scaled_momentum",
    "fixed_feature_score",
    "regularized_logistic",
    "cpu_xgboost",
})


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _timestamp(value: Any, name: str) -> pd.Timestamp:
    if value is None:
        raise ValueError(f"{name} is required")
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return result.tz_convert(timezone.utc)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


def load_frozen_artifact(artifact: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    """Load and validate a frozen research artifact without opening holdout data."""
    if isinstance(artifact, (str, Path)):
        raw = json.loads(Path(artifact).read_text(encoding="utf-8"))
    else:
        raw = dict(artifact)
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported daily directional artifact schema")
    if not isinstance(raw.get("experiment_id"), str) or not raw["experiment_id"]:
        raise ValueError("artifact experiment_id is required")
    if raw.get("broker_authorized") is not False:
        raise ValueError("artifact scorer accepts shadow-only, non-broker artifacts only")
    terminal = _mapping(raw.get("terminal_holdout"), "terminal_holdout")
    # A later promotion process may write evaluated gate metadata, but this
    # scorer never loads its observations.  Any other status is ambiguous and
    # therefore rejected rather than inferred.
    if terminal.get("status") not in {"SEALED_UNEVALUATED", "EVALUATED"}:
        raise ValueError("artifact terminal holdout status must be sealed or evaluated")
    horizons = _mapping(raw.get("horizons"), "horizons")
    if not horizons:
        raise ValueError("artifact horizons are required")
    for key, value in horizons.items():
        horizon = int(key)
        item = _mapping(value, f"horizons.{key}")
        if horizon < 1 or item.get("horizon_days") != horizon:
            raise ValueError(f"invalid horizon metadata: {key}")
        if not isinstance(item.get("probability_target"), str) or not item["probability_target"].startswith("underlying_"):
            raise ValueError(f"horizon {key} must state an underlying probability target")
        calibration = _mapping(item.get("calibration"), f"horizons.{key}.calibration")
        _finite(calibration.get("coefficient"), "calibration.coefficient")
        _finite(calibration.get("intercept"), "calibration.intercept")
        if not isinstance(calibration.get("version"), str) or not calibration["version"]:
            raise ValueError("calibration.version is required")
        threshold = _finite(item.get("threshold"), "threshold")
        if not .5 <= threshold < 1.0:
            raise ValueError("threshold must be in [0.5, 1)")
        model = _mapping(item.get("model"), f"horizons.{key}.model")
        if model.get("type") not in _MODEL_TYPES:
            raise ValueError(f"unsupported serialized model type: {model.get('type')}")
    return raw


def _features(features: Mapping[str, Any], names: list[str], *, asof_utc: datetime | pd.Timestamp) -> np.ndarray:
    _timestamp(features.get("feature_asof"), "feature_asof")
    feature_asof = _timestamp(features["feature_asof"], "feature_asof")
    asof = _timestamp(asof_utc, "asof_utc")
    if feature_asof > asof:
        raise ValueError("future feature_asof is not scoreable")
    values = []
    for name in names:
        if name not in features:
            raise ValueError(f"missing required feature: {name}")
        values.append(_finite(features[name], f"feature {name}"))
    return np.asarray(values, dtype=float)


def _raw_score(model: Mapping[str, Any], features: Mapping[str, Any], *, asof_utc: datetime | pd.Timestamp) -> float:
    kind = str(model["type"])
    if kind in {"momentum", "volatility_scaled_momentum", "fixed_feature_score"}:
        feature = model.get("score_feature")
        if not isinstance(feature, str) or not feature:
            raise ValueError("serialized baseline score_feature is required")
        return float(_features(features, [feature], asof_utc=asof_utc)[0])
    names = model.get("features")
    if not isinstance(names, list) or not names or not all(isinstance(name, str) and name for name in names):
        raise ValueError("serialized model features must be a non-empty string list")
    values = _features(features, names, asof_utc=asof_utc)
    if kind == "regularized_logistic":
        mean = np.asarray(model.get("scaler_mean"), dtype=float)
        scale = np.asarray(model.get("scaler_scale"), dtype=float)
        coefficient = np.asarray(model.get("coefficient"), dtype=float)
        if any(array.shape != values.shape for array in (mean, scale, coefficient)) or not np.isfinite([*mean, *scale, *coefficient]).all():
            raise ValueError("malformed serialized logistic arrays")
        if np.any(scale <= 0):
            raise ValueError("serialized logistic scaler_scale must be positive")
        return float(np.dot((values - mean) / scale, coefficient) + _finite(model.get("intercept"), "logistic intercept"))
    # XGBoost model bytes are only decoded after all feature/timestamp checks.
    if model.get("booster_format") != "xgboost-json-base64" or not isinstance(model.get("booster_bytes_base64"), str):
        raise ValueError("malformed serialized XGBoost booster")
    try:
        import xgboost as xgb
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("xgboost is unavailable; artifact scoring fails closed") from exc
    try:
        booster_bytes = base64.b64decode(model["booster_bytes_base64"], validate=True)
        booster = xgb.Booster()
        booster.load_model(bytearray(booster_bytes))
        probability = float(booster.predict(xgb.DMatrix(values.reshape(1, -1), feature_names=names))[0])
    except Exception as exc:
        raise ValueError("malformed serialized XGBoost booster") from exc
    if not 0.0 < probability < 1.0 or not math.isfinite(probability):
        raise ValueError("serialized XGBoost probability is invalid")
    return float(math.log(probability / (1.0 - probability)))


def score_frozen_artifact(artifact: str | Path | Mapping[str, Any], features: Mapping[str, Any], *,
                          horizon_days: int, asof_utc: datetime | pd.Timestamp) -> dict[str, Any]:
    """Apply stored model, Platt map, and threshold to point-in-time features.

    The result intentionally remains WATCH/shadow-only.  Passing an underlying
    evidence gate is not an option-profit claim and cannot authorize execution.
    """
    frozen = load_frozen_artifact(artifact)
    item = _mapping(frozen["horizons"].get(str(int(horizon_days))), f"horizons.{horizon_days}")
    model = _mapping(item["model"], "model")
    score = _raw_score(model, features, asof_utc=asof_utc)
    calibration = _mapping(item["calibration"], "calibration")
    logit = _finite(calibration["coefficient"], "calibration.coefficient") * score + _finite(calibration["intercept"], "calibration.intercept")
    probability = float(1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, logit)))))
    threshold = float(item["threshold"])
    eligible = True
    eligibility_feature = model.get("eligibility_feature")
    if eligibility_feature is not None:
        if not isinstance(eligibility_feature, str) or eligibility_feature not in features:
            raise ValueError("serialized fixed feature model eligibility_feature is required")
        eligibility_value = features[eligibility_feature]
        if not isinstance(eligibility_value, (bool, np.bool_)):
            raise ValueError("eligibility feature must be boolean")
        eligible = bool(eligibility_value)
    if model["type"] == "fixed_feature_score":
        side = "long" if eligible and score > 0 else "short" if eligible and score < 0 else "neutral"
    else:
        side = (
            "long" if eligible and probability >= threshold
            else "short" if eligible and probability <= 1.0 - threshold
            else "neutral"
        )
    passed_underlying_gate = str(frozen.get("underlying_gate", "")).upper() in {"PASS", "PASSED"}
    return {
        "artifact_id": frozen["experiment_id"],
        "state": "WATCH",
        "shadow_only": True,
        "broker_authorized": False,
        "underlying_gate_passed": passed_underlying_gate,
        "side": side,
        "eligible": eligible,
        "probability": probability,
        "calibrated_probability": probability,
        "probability_target": item["probability_target"],
        "horizon_days": int(item["horizon_days"]),
        "calibration_version": calibration["version"],
        "threshold": threshold,
        "model_type": model["type"],
    }
