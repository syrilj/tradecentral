from datetime import datetime, timezone
import json

import pytest

from edge.daily_plays.monitoring import shadow_report
from edge.daily_plays.realize import realize_due_decisions
from edge.daily_plays.schedule import ScheduleAlreadyRunning, run_locked
from edge.daily_plays.shadow_lifecycle import append_option_entries, mark_open_option_positions


ASOF = "2026-07-01T14:00:00Z"


def _decision(play_id="r:NVDA:long_call", *, probability=.7, state="ENTER"):
    return {"run_id": "r", "requested_for": "2026-07-01", "asof_utc": ASOF, "mode": "replay", "plays": [{
        "play_id": play_id, "side": "long", "state": state,
        "entry": {"underlying_reference": 100}, "provenance": {"shadow_horizon_days": 5},
        "confidence": {"confidence_kind": "calibrated_probability", "calibrated_probability": probability},
    }]}


def test_realization_is_due_only_idempotent_and_fail_closed(tmp_path):
    (tmp_path / "shadow_decisions.jsonl").write_text(json.dumps(_decision()) + "\n")
    calls = []
    def provider(**kwargs):
        calls.append(kwargs["play"]["play_id"])
        return {"price": 110, "asof_utc": "2026-07-06T14:00:00Z"}
    early = realize_due_decisions(output_root=tmp_path, provider=provider, asof_utc=datetime(2026, 7, 5, 13, tzinfo=timezone.utc))
    assert early["pending"] == 1 and not calls
    done = realize_due_decisions(output_root=tmp_path, provider=provider, asof_utc=datetime(2026, 7, 7, tzinfo=timezone.utc))
    assert done["realized"] == 1
    assert realize_due_decisions(output_root=tmp_path, provider=provider, asof_utc=datetime(2026, 7, 7, tzinfo=timezone.utc))["realized"] == 0
    assert len((tmp_path / "shadow_outcomes.jsonl").read_text().splitlines()) == 1


def test_realization_rejects_missing_or_pre_horizon_outcome_timestamp(tmp_path):
    (tmp_path / "shadow_decisions.jsonl").write_text(json.dumps(_decision()) + "\n")
    result = realize_due_decisions(output_root=tmp_path, provider=lambda **_: {"price": 110, "asof_utc": "2026-07-02T14:00:00Z"},
                                   asof_utc=datetime(2026, 7, 7, tzinfo=timezone.utc))
    assert result["realized"] == 0 and result["errors"]
    assert not (tmp_path / "shadow_outcomes.jsonl").exists()


def test_report_calibration_expectancy_and_readiness(tmp_path):
    (tmp_path / "shadow_decisions.jsonl").write_text(json.dumps(_decision()) + "\n")
    (tmp_path / "shadow_outcomes.jsonl").write_text(json.dumps({"play_id": "r:NVDA:long_call", "confidence_kind": "calibrated_probability", "calibrated_probability": .7, "outcome": True, "gross_return_pct": 10}) + "\n")
    report = shadow_report(output_root=tmp_path, spread_bps=10, slippage_bps=5)
    assert report["brier_score"] == pytest.approx(.09)
    assert report["realized_expectancy_pct"] == pytest.approx(9.85)
    assert not report["readiness_checklist"]["ready"]
    assert report["promotion_gate"]["status"] == "FAIL_SHADOW_ONLY"


def test_schedule_lock_is_exclusive_and_released(tmp_path):
    lock = tmp_path / ".daily_plays_scheduler.lock"
    lock.write_text("other")
    with pytest.raises(ScheduleAlreadyRunning): run_locked(lambda: None, output_root=tmp_path)
    lock.unlink()
    assert run_locked(lambda: "ok", output_root=tmp_path) == "ok"
    assert not lock.exists()


OPTION_ASOF = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)


def _option_play(**changes):
    play = {"play_id": "r:NVDA:long_call", "state": "ENTER", "legs": [{
        "side": "buy", "underlying": "NVDA", "right": "call", "expiry": "2026-08-04", "strike": 180,
        "occ_symbol": "NVDA260804C00180000", "multiplier": 100, "bid": 4.5, "ask": 5.0,
        "quote_asof_utc": "2026-08-03T13:59:45Z", "provider": "lse", "delta": .5, "gamma": .02, "iv": .4,
    }]}
    play.update(changes)
    return play


def _option_quote(**changes):
    quote = {"occ_symbol": "NVDA260804C00180000", "multiplier": 100, "bid": 5.5, "ask": 5.7,
             "quote_asof_utc": "2026-08-04T13:59:50Z", "provider": "lse", "delta": .52, "gamma": .025, "iv": .38}
    quote.update(changes)
    return quote


def test_option_lifecycle_persists_exact_entry_daily_mark_expiration_exit_and_is_idempotent(tmp_path):
    entered = append_option_entries(output_root=tmp_path, plays=[_option_play()], asof_utc=OPTION_ASOF)
    assert entered == {"entered": 1, "entry_abstentions": 0}
    assert append_option_entries(output_root=tmp_path, plays=[_option_play()], asof_utc=OPTION_ASOF)["entered"] == 0
    position = json.loads((tmp_path / "shadow_option_positions.jsonl").read_text())
    assert position["occ_symbol"] == "NVDA260804C00180000"
    assert position["entry_fill_per_share"] == 5.0  # ask-to-enter
    assert position["shadow_only"] is True and position["broker_order_id"] is None

    result = mark_open_option_positions(output_root=tmp_path, provider=lambda **_: _option_quote(),
                                        asof_utc=datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc))
    assert result["marked"] == 1 and result["closed"] == 1 and result["unresolved"] == 0
    assert mark_open_option_positions(output_root=tmp_path, provider=lambda **_: _option_quote(),
                                      asof_utc=datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc))["marked"] == 0
    mark = json.loads((tmp_path / "shadow_option_marks.jsonl").read_text())
    assert mark["nbbo"]["bid"] == 5.5 and mark["nbbo"]["ask"] == 5.7 and mark["nbbo"]["mid"] == 5.6
    assert mark["nbbo"]["greeks"] == {"delta": .52, "gamma": .025} and mark["nbbo"]["iv"] == .38
    outcome = json.loads((tmp_path / "shadow_option_outcomes.jsonl").read_text())
    assert outcome["exit_reason"] == "expiration" and outcome["exit_fill_per_share"] == 5.5  # bid-to-exit
    assert outcome["realized_pnl_dollars"] == 50 and outcome["mae_dollars"] == 0 and outcome["mfe_dollars"] == 50


@pytest.mark.parametrize("reason, quote", [
    ("stale_quote", _option_quote(quote_asof_utc="2026-08-03T13:00:00Z")),
    ("missing_bid_or_ask", _option_quote(ask=None)),
    ("crossed_market", _option_quote(bid=5.8, ask=5.7)),
    ("unavailable_greeks", _option_quote(gamma=None)),
    ("missing_or_invalid_iv", _option_quote(iv=None)),
    ("split_adjusted_contract", _option_quote(split_adjusted=True)),
    ("nonstandard_contract_multiplier", _option_quote(multiplier=50)),
])
def test_option_lifecycle_marks_fail_closed_and_persist_unresolved_status(tmp_path, reason, quote):
    append_option_entries(output_root=tmp_path, plays=[_option_play()], asof_utc=OPTION_ASOF)
    result = mark_open_option_positions(output_root=tmp_path, provider=lambda **_: quote,
                                        asof_utc=datetime(2026, 8, 4, 14, tzinfo=timezone.utc))
    assert result["marked"] == 0 and result["closed"] == 0 and result["unresolved"] == 1
    event = json.loads((tmp_path / "shadow_option_lifecycle.jsonl").read_text())
    assert event["status"] == "UNRESOLVED" and event["reason"] == reason
    assert not (tmp_path / "shadow_option_outcomes.jsonl").exists()


def test_option_lifecycle_provider_outage_and_legacy_realization_cannot_create_option_pnl(tmp_path):
    append_option_entries(output_root=tmp_path, plays=[_option_play()], asof_utc=OPTION_ASOF)
    result = mark_open_option_positions(output_root=tmp_path, provider=lambda **_: None,
                                        asof_utc=datetime(2026, 8, 4, 14, tzinfo=timezone.utc))
    assert result["unresolved"] == 1
    event = json.loads((tmp_path / "shadow_option_lifecycle.jsonl").read_text())
    assert event["reason"] == "provider_outage_or_quote_unavailable"

    decision = _decision(); decision["plays"][0]["legs"] = _option_play()["legs"]
    (tmp_path / "shadow_decisions.jsonl").write_text(json.dumps(decision) + "\n")
    underlying = realize_due_decisions(output_root=tmp_path, provider=lambda **_: {"price": 110, "asof_utc": "2026-07-06T14:00:00Z"},
                                        asof_utc=datetime(2026, 7, 7, tzinfo=timezone.utc))
    assert underlying["realized"] == 0
    assert any(row["error"] == "option_lifecycle_required" for row in underlying["errors"])
