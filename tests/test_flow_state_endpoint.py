from __future__ import annotations

import json

from edge.tools import api_server


def _write_latest(tmp_path, monkeypatch, content: str) -> None:
    monkeypatch.setattr(api_server, "FLOW_STATE_DIR", tmp_path)
    (tmp_path / "latest.json").write_text(content, encoding="utf-8")


def test_missing_artifact_is_unavailable_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "FLOW_STATE_DIR", tmp_path)

    payload = api_server._flow_state_payload()

    assert payload["available"] is False
    assert payload["reason"] is not None
    assert "flow_state" in payload["reason"] or "latest.json" in payload["reason"]
    assert payload["tier"] == 0
    assert payload["decision_authorized"] is False
    assert payload["models"] is None
    assert payload["producing_script"] == "tools/build_flow_state.py"


def test_missing_artifact_still_has_every_pinned_key(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "FLOW_STATE_DIR", tmp_path)

    payload = api_server._flow_state_payload()

    for key in (
        "available", "reason", "as_of", "tier", "decision_authorized", "caveats",
        "states", "timelines", "events", "barrier_fields", "impact_curve",
        "phenomenon", "gate", "models", "producing_script",
    ):
        assert key in payload
    for key in ("tested", "effect", "nw_t", "boot_ci", "perm_p", "n_events", "n_controls", "grid", "prereg_id", "passed"):
        assert key in payload["phenomenon"]
    for key in ("evaluated", "passed", "checks", "ledger_id"):
        assert key in payload["gate"]
    for key in ("lags", "mean_cum_ret", "ci_lo", "ci_hi"):
        assert key in payload["impact_curve"]


def test_malformed_json_never_raises(tmp_path, monkeypatch):
    _write_latest(tmp_path, monkeypatch, "{not valid json")

    payload = api_server._flow_state_payload()

    assert payload["available"] is False
    assert "unreadable" in payload["reason"]


def test_non_object_json_is_unavailable(tmp_path, monkeypatch):
    _write_latest(tmp_path, monkeypatch, json.dumps([1, 2, 3]))

    payload = api_server._flow_state_payload()

    assert payload["available"] is False
    assert "not a JSON object" in payload["reason"]


def test_valid_payload_passes_through_and_fills_absent_keys(tmp_path, monkeypatch):
    partial = {
        "available": True,
        "as_of": "2026-07-10",
        "tier": 1,
        "decision_authorized": False,
        "states": [{"symbol": "AAPL", "current_state": "SHOCK", "stress_rank": 1}],
        "producing_script": "tools/build_flow_state.py",
        # "phenomenon", "gate", "events", "timelines", "barrier_fields",
        # "impact_curve", "caveats", "models" deliberately omitted -- the
        # endpoint must fill them from `empty`, not error out.
    }
    _write_latest(tmp_path, monkeypatch, json.dumps(partial))

    payload = api_server._flow_state_payload()

    assert payload["available"] is True
    assert payload["as_of"] == "2026-07-10"
    assert payload["tier"] == 1
    assert payload["states"][0]["symbol"] == "AAPL"
    # Absent keys are filled from `empty`, not dropped.
    assert payload["events"] == []
    assert payload["timelines"] == {}
    assert payload["barrier_fields"] == {}
    assert payload["models"] is None
    assert payload["gate"] == {"evaluated": False, "passed": False, "checks": {}, "ledger_id": None}


def test_explicit_available_false_with_reason_is_preserved(tmp_path, monkeypatch):
    partial = {"available": False, "reason": "panel is empty (no symbols resolved)"}
    _write_latest(tmp_path, monkeypatch, json.dumps(partial))

    payload = api_server._flow_state_payload()

    assert payload["available"] is False
    assert payload["reason"] == "panel is empty (no symbols resolved)"
    # Every other pinned key still present even in the false-availability case.
    assert payload["states"] == []
    assert payload["caveats"] == []


def test_genuinely_computed_null_is_not_papered_over(tmp_path, monkeypatch):
    """A real (non-missing) null value from the artifact must survive the
    merge -- e.g. `as_of: null` on a degenerate but technically-available
    run must not be silently replaced by some other default."""
    partial = {"available": True, "as_of": None, "tier": 0, "states": []}
    _write_latest(tmp_path, monkeypatch, json.dumps(partial))

    payload = api_server._flow_state_payload()

    assert payload["available"] is True
    assert payload["as_of"] is None
