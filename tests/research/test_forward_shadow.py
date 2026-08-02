from __future__ import annotations

import math

import pytest

from edge.research.forward_shadow import ForwardShadowLedger, normalize_forward_forecast


def _forecast(**changes):
    record = {
        "artifact_id": "daily-artifact-v1", "symbol": "nvda", "feature_asof": "2026-07-30T20:00:00Z",
        "generated_at": "2026-07-30T20:01:00Z", "horizon_days": 10,
        "probability_target": "underlying_directional_return_next_open_to_horizon_close",
        "calibration_version": "platt-v1", "side": "long", "probability": .71, "threshold": .60,
        "state": "WATCH", "shadow_only": True,
    }
    record.update(changes)
    return record


def test_forward_watch_forecast_is_canonical_hashed_and_idempotent(tmp_path) -> None:
    ledger = ForwardShadowLedger(tmp_path / "forward_shadow.jsonl")
    first = ledger.append(_forecast())
    replay = ledger.append(_forecast())
    reopened = ForwardShadowLedger(tmp_path / "forward_shadow.jsonl")
    assert first == replay == reopened.records[0]
    assert first.forecast["symbol"] == "NVDA"
    assert first.forecast["feature_asof"].endswith("Z")
    assert len((tmp_path / "forward_shadow.jsonl").read_text().splitlines()) == 1


def test_forward_forecast_conflict_is_append_only_not_a_second_record(tmp_path) -> None:
    ledger = ForwardShadowLedger(tmp_path / "forward_shadow.jsonl")
    ledger.append(_forecast())
    with pytest.raises(ValueError, match="append-only conflict"):
        ledger.append(_forecast(probability=.72))
    assert len(ledger.records) == 1


@pytest.mark.parametrize("changes, message", [
    ({"state": "ENTER"}, "WATCH shadow"), ({"shadow_only": False}, "WATCH shadow"),
    ({"feature_asof": "2026-07-30T20:02:00Z"}, "cannot be after"),
    ({"probability": math.nan}, "finite probability"), ({"threshold": 1.1}, "finite probability"),
    ({"threshold": .49}, r"\[0.5, 1\)"),
    ({"horizon_days": 8}, "horizon_days"), ({"probability_target": "option_profit"}, "underlying"),
    ({"outcome": True}, "extra"),
])
def test_forward_ledger_rejects_actionable_future_malformed_and_outcome_payloads(changes, message) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_forward_forecast(_forecast(**changes))


def test_forward_ledger_has_no_outcome_or_market_realization_interface(tmp_path) -> None:
    ledger = ForwardShadowLedger(tmp_path / "forward_shadow.jsonl")
    assert not hasattr(ledger, "realize")
    assert not hasattr(ledger, "outcome_for")
