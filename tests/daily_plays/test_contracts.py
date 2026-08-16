from datetime import date, datetime, timezone

import pytest

from edge.daily_plays.contracts import (
    Confidence, ConfidenceKind, EvidenceGrade, LegSide, OptionLeg,
    OptionRight, PlayState, canonical_json, stable_hash,
)


def test_canonical_json_and_hash_are_deterministic():
    value = {"when": datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc), "symbols": ["NVDA"]}
    assert canonical_json(value) == '{"symbols":["NVDA"],"when":"2026-07-30T14:05:00Z"}'
    assert stable_hash(value) == stable_hash({"symbols": ["NVDA"], "when": value["when"]})


def test_option_leg_rejects_missing_exact_identity():
    with pytest.raises(ValueError, match="missing identity"):
        OptionLeg(LegSide.BUY, OptionRight.CALL, "", "NVDA", date(2026, 8, 21), 22,
                  180, 100, 1, 1.1, 1.05, .1, 10, 100,
                  datetime.now(timezone.utc), "lse")


def test_ordinal_confidence_cannot_emit_enter():
    with pytest.raises(ValueError, match="ENTER requires"):
        Confidence(PlayState.ENTER, ConfidenceKind.ORDINAL_SCORE, EvidenceGrade.B)


def test_enter_requires_underlying_probability_target_and_positive_horizon():
    with pytest.raises(ValueError, match="target semantics"):
        Confidence(PlayState.ENTER, ConfidenceKind.CALIBRATED_PROBABILITY, EvidenceGrade.A,
                   calibrated_probability=.7)
    confidence = Confidence(PlayState.ENTER, ConfidenceKind.CALIBRATED_PROBABILITY, EvidenceGrade.A,
                            calibrated_probability=.7, probability_target="underlying_directional_return",
                            horizon_days=10, entry_threshold=.65, threshold_version="gate-v1",
                            model_artifact_sha256="a" * 64, promotion_authorized=True)
    assert confidence.horizon_days == 10


def test_option_profit_cannot_be_used_as_probability_target():
    with pytest.raises(ValueError, match="underlying event"):
        Confidence(PlayState.WATCH, ConfidenceKind.CALIBRATED_PROBABILITY, EvidenceGrade.B,
                   calibrated_probability=.7, probability_target="option_profit", horizon_days=10)
