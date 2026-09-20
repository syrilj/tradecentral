from __future__ import annotations

import pytest

from research import typesafe_live_decision as live


def _state(*, may_enter: bool = True) -> dict:
    return {
        "symbol": "SPY",
        "observed_at": "2026-09-20T18:00:00Z",
        "source_status": {
            "options": "ready",
            "regime": "ready",
            "microstructure": "ready",
            "vpa": "ready",
            "execution_gate": "ready",
        },
        "options": {
            "activity_lean": "bullish",
            "signed_flow_imbalance": 0.44,
            "gex_regime": "negative",
        },
        "regime": {"primary": "bull_trend", "transition_risk": "low"},
        "microstructure": {"measurable": True, "regime": "negative_gamma"},
        "vpa": {"bias": "LONG", "market_phase": "markup"},
        "execution_gate": {
            "may_enter": may_enter,
            "must_be_flat": False,
            "reason": "Regular session" if may_enter else "Entries closed",
        },
    }


def test_request_batches_independent_typed_judgments():
    request = live.build_typesafe_request(_state())

    assert request["model"] == "jev-latest"
    assert set(request["questions"]) == {"lean", "action", "setup", "alignment", "timing", "risk"}
    assert request["questions"]["action"]["type"] == "choice"
    assert request["questions"]["alignment"]["type"] == "score"
    assert request["questions"]["action"]["criteria"]["wait"]


def test_conservative_fallback_can_surface_aligned_buy_without_authorizing(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")

    result = live.evaluate_live_decision(_state())

    assert result["engine"]["mode"] == "deterministic_fallback"
    assert result["action"] == "buy"
    assert result["decision_authorized"] is False
    assert result["blockers"] == []


def test_execution_gate_overrides_directional_model_answer(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")

    result = live.evaluate_live_decision(_state(may_enter=False))

    assert result["raw_action"] == "buy"
    assert result["action"] == "wait"
    assert "Entries closed" in result["blockers"]


def test_typesafe_answers_are_parsed_but_final_policy_remains_in_code(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    answers = {
        "action": {
            "type": "choice",
            "choice": "sell",
            "confidence": 0.86,
            "probabilities": {"buy": 0.06, "sell": 0.86, "wait": 0.08},
        },
        "setup": {
            "type": "choice",
            "choice": "breakout",
            "confidence": 0.7,
            "probabilities": {"breakout": 0.7, "no_setup": 0.3},
        },
        "alignment": {"type": "score", "score": 3.1, "confidence": 0.8},
        "timing": {"type": "score", "score": 3.0, "confidence": 0.75},
        "risk": {"type": "score", "score": 2.1, "confidence": 0.65},
    }
    monkeypatch.setattr(live, "_call_typesafe", lambda payload, key: (answers, "jev-test", 17))

    result = live.evaluate_live_decision(_state())

    assert result["engine"] == {
        "provider": "typesafe",
        "mode": "typesafe",
        "model": "jev-test",
        "configured": True,
        "latency_ms": 17,
        "error": None,
    }
    assert result["action"] == "sell"
    assert result["setup"] == "breakout"
    assert result["decision_authorized"] is False


def test_invalid_symbol_is_rejected():
    with pytest.raises(ValueError, match="symbol"):
        live.evaluate_live_decision({"symbol": "../not-a-ticker"})


@pytest.fixture
def cached_provider(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "cache-test-key")
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "15")
    live._CACHE.clear()
    calls = []

    def call(payload, key):
        import time

        time.sleep(0.02)
        calls.append(payload)
        return live._local_judgments(payload["state"]), "jev-test", 20

    monkeypatch.setattr(live, "_call_typesafe", call)
    return calls


def test_refresh_timestamp_reuses_evidence_but_preserves_observation(cached_provider):
    first = live.evaluate_live_decision(_state())
    state = _state()
    state["observed_at"] = "2026-09-20T18:00:01Z"
    second = live.evaluate_live_decision(state)
    assert len(cached_provider) == 1
    assert second["cache"]["hit"] is True
    assert second["observed_at"] == state["observed_at"]
    assert second["asof_utc"] == first["asof_utc"]


def test_concurrent_tabs_share_one_request(cached_provider):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: live.evaluate_live_decision(_state()), range(8)))
    assert len(cached_provider) == 1
    assert sum(not result["cache"]["hit"] for result in results) == 1


@pytest.mark.parametrize("change", ["gate", "freshness", "source_timestamp", "key"])
def test_material_changes_invalidate_cache(cached_provider, monkeypatch, change):
    live.evaluate_live_decision(_state())
    state = _state()
    if change == "gate":
        state["execution_gate"]["may_enter"] = False
    elif change == "freshness":
        state["options"]["feed_age_seconds"] = 300
    elif change == "source_timestamp":
        state["options"]["asof"] = "2026-09-20T18:00:02Z"
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", "rotated-test-key")
    result = live.evaluate_live_decision(state)
    assert len(cached_provider) == 2
    assert result["cache"]["hit"] is False
    if change == "gate":
        assert result["action"] == "wait"


def test_http_auth_failure_is_identifiable_without_credentials(monkeypatch):
    from urllib.error import HTTPError

    def fail(*args, **kwargs):
        assert kwargs["context"].check_hostname is True
        raise HTTPError(live.TYPESAFE_ENDPOINT, 401, "private response", {}, None)

    monkeypatch.setattr(live, "urlopen", fail)
    with pytest.raises(RuntimeError, match="HTTP 401") as error:
        live._call_typesafe(live.build_typesafe_request(_state()), "secret-test-key")
    assert "secret-test-key" not in str(error.value)


def test_expired_cache_calls_provider_again(cached_provider, monkeypatch):
    live.evaluate_live_decision(_state())
    monkeypatch.setattr(live.time, "monotonic", lambda: float("inf"))
    result = live.evaluate_live_decision(_state())
    assert len(cached_provider) == 2
    assert result["cache"]["hit"] is False


def test_cache_results_cannot_be_mutated_by_callers(cached_provider):
    first = live.evaluate_live_decision(_state())
    first["source_status"]["options"] = "corrupted"
    second = live.evaluate_live_decision(_state())
    assert second["source_status"]["options"] == "ready"


def test_wait_preserves_directional_lean(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = live.evaluate_live_decision(_state(may_enter=False))
    assert result["action"] == "wait"
    assert result["lean"] == "bullish"


def test_missing_sources_do_not_create_fallback_lean(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    state = _state()
    state["source_status"] = {}
    result = live.evaluate_live_decision(state)
    assert result["lean"] == "unknown"
    assert result["action"] == "wait"
