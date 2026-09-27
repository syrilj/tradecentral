import json
from pathlib import Path

from edge.daily_plays.adapters.internal_models import normalize_internal_model_payload


FIXTURES = Path(__file__).parent / "fixtures"


def test_normalizes_explicit_calibrated_live_plan_probability():
    result = normalize_internal_model_payload(json.loads((FIXTURES / "live_plan_calibrated.json").read_text()))
    assert result["side"] == "long"
    assert result["model"]["confidence_kind"] == "calibrated_probability"
    assert result["model"]["probability"] == 0.71
    assert result["model"]["probability_target"] is None
    assert result["model"]["horizon_days"] is None


def test_uncalibrated_value_is_ordinal_not_probability():
    result = normalize_internal_model_payload({"symbol": "X", "model": {"raw_probability": 0.99}, "confidence": {"uncalibrated": True}})
    assert result["model"]["confidence_kind"] == "ordinal_score"
    assert result["model"]["probability"] is None
    assert result["model"]["raw_score"] == 0.99
