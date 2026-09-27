from __future__ import annotations

from datetime import timedelta, timezone
import json

import numpy as np
import pandas as pd
import pytest

from edge.daily_plays.monitoring import shadow_report
from edge.daily_plays.promotion import underlying_gate_authorization


def _full_shadow_history() -> tuple[list[dict], list[dict]]:
    decisions: list[dict] = []
    outcomes: list[dict] = []
    sessions = pd.bdate_range("2024-01-02", periods=200)
    symbols = ("AAA", "BBB", "CCC", "DDD")
    regimes = (("LOW", "UP"), ("LOW", "DOWN"), ("HIGH", "UP"), ("HIGH", "DOWN"))
    for index, session in enumerate(sessions):
        asof = session.to_pydatetime().replace(hour=14, tzinfo=timezone.utc)
        due = asof + timedelta(days=5)
        play_id = f"shadow-{index}"
        volatility, trend = regimes[index % len(regimes)]
        decisions.append({
            "run_id": f"run-{index}", "requested_for": session.date().isoformat(),
            "asof_utc": asof.isoformat().replace("+00:00", "Z"), "warnings": [],
            "plays": [{
                "play_id": play_id, "state": "ENTER", "symbol": symbols[index % len(symbols)],
                "legs": [{"occ_symbol": f"{symbols[index % len(symbols)]}250117C00100000"}],
                "evidence": {"volatility_regime": volatility, "trend_regime": trend},
            }],
        })
        # Variation avoids a zero-volatility Sharpe while all outcomes remain profitable.
        net_return = 2.0 + 0.2 * np.sin(index)
        outcomes.append({
            "play_id": play_id, "confidence_kind": "calibrated_probability",
            "calibrated_probability": 0.99, "outcome": True,
            "gross_return_pct": net_return, "ask_to_bid_net_return_pct": net_return,
            "due_utc": due.isoformat().replace("+00:00", "Z"),
            "outcome_asof_utc": due.isoformat().replace("+00:00", "Z"),
            "drift_stable": True,
        })
    return decisions, outcomes


def _write_jsonl(path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_full_preregistered_shadow_history_passes_only_shadow_promotion(tmp_path) -> None:
    decisions, outcomes = _full_shadow_history()
    _write_jsonl(tmp_path / "shadow_decisions.jsonl", decisions)
    _write_jsonl(tmp_path / "shadow_outcomes.jsonl", outcomes)
    report = shadow_report(output_root=tmp_path, recorded_trial_count=3)
    readiness = report["readiness_checklist"]
    promotion = report["promotion_gate"]
    assert readiness["ready"]
    assert readiness["distinct_sessions"] == 200
    assert readiness["completed_shadow_option_trades"] == 200
    assert readiness["observed_regimes"] == 4
    assert promotion["passed"]
    assert promotion["status"] == "PASS_SHADOW_ONLY"
    assert not promotion["live_capital_authorized"]
    assert not promotion["broker_connectivity_authorized"]
    assert promotion["metrics"]["bootstrap_lower_bound_pct"] > 0
    assert promotion["metrics"]["deflated_sharpe_lower_bound"] > 0


def test_missing_trial_count_or_drift_is_fail_closed(tmp_path) -> None:
    decisions, outcomes = _full_shadow_history()
    _write_jsonl(tmp_path / "shadow_decisions.jsonl", decisions)
    _write_jsonl(tmp_path / "shadow_outcomes.jsonl", outcomes)
    no_trials = shadow_report(output_root=tmp_path)
    assert not no_trials["promotion_gate"]["passed"]
    assert "recorded_trial_count" in no_trials["promotion_gate"]["failed_checks"]
    outcomes[0].pop("drift_stable")
    _write_jsonl(tmp_path / "shadow_outcomes.jsonl", outcomes)
    unstable = shadow_report(output_root=tmp_path, recorded_trial_count=3)
    assert not unstable["promotion_gate"]["passed"]
    assert "drift_stable" in unstable["promotion_gate"]["failed_checks"]


def test_readiness_threshold_cannot_be_lowered_and_underlying_authorizes_shadow_only(tmp_path) -> None:
    with pytest.raises(ValueError, match="frozen at 120"):
        shadow_report(output_root=tmp_path, required_sessions=1)
    authorized = underlying_gate_authorization(True)
    rejected = underlying_gate_authorization(False)
    assert authorized["shadow_collection_authorized"]
    assert not authorized["live_capital_authorized"]
    assert not authorized["broker_connectivity_authorized"]
    assert not rejected["shadow_collection_authorized"]
