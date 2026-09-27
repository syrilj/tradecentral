from __future__ import annotations

import json

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
    assert set(request["questions"]) == {
        "lean",
        "action",
        "setup",
        "alignment",
        "timing",
        "risk",
        "vpa_direction",
        "vpa_claim_support",
    }
    assert request["questions"]["action"]["type"] == "choice"
    assert request["questions"]["alignment"]["type"] == "score"
    assert set(request["questions"]["action"]["criteria"]) == {"buy", "sell"}
    assert "wait" not in request["questions"]["action"]["criteria"]
    assert set(request["questions"]["vpa_direction"]["criteria"]) == {"buy", "sell"}
    assert request["questions"]["vpa_claim_support"]["type"] == "score"
    assert len(request["questions"]["vpa_claim_support"]["criteria"]) == 5


def test_request_labels_kronos_as_advisory_research_only():
    request = live.build_typesafe_request(live._compact_state(_state()))
    state = request["state"]
    assert state["source_status"]["forecast"] == "missing"
    assert set(state["forecast"]) == {
        "source",
        "asof_utc",
        "direction",
        "horizon",
        "point_pct",
        "interval_80",
        "confidence_kind",
        "confidence_score",
        "confidence_label",
        "selective_actionable",
        "provenance",
    }
    for question in ("lean", "action"):
        instructions = request["questions"][question]["instructions"].lower()
        assert "unvalidated ordinal research" in instructions
        assert "independent confirmation" in instructions
        assert "win probability" in instructions
    assert "determine this action" in request["questions"]["action"]["instructions"]


def test_conservative_fallback_can_surface_aligned_buy_without_authorizing(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")

    result = live.evaluate_live_decision(_state())

    assert result["schema_version"] == "typesafe-live-decision-v2"
    assert result["engine"]["mode"] == "deterministic_fallback"
    assert result["action"] == "buy"
    assert result["decision_authorized"] is False
    assert result["blockers"] == []
    assert result["risk_assessment"]["keep_out"] is False
    assert "wait" not in result["probabilities"]
    assert set(result["probabilities"]) == {"buy", "sell"}
    assert result["vpa_judgment"]["direction"] == "buy"


def test_forecast_evidence_is_always_present_with_missing_contract(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")

    result = live.evaluate_live_decision(_state())

    assert result["forecast_evidence"] == {
        "status": "missing",
        "available": False,
        "reason": "Kronos evidence is unavailable for this session.",
        "source": None,
        "asof_utc": None,
        "direction": None,
        "horizon": None,
        "point_pct": None,
        "interval_80": None,
        "confidence_kind": None,
        "confidence_score": None,
        "confidence_label": None,
        "selective_actionable": False,
        "provenance": {},
        "conflict_with_action": False,
    }


def test_ready_forecast_conflict_only_adds_advisory_risk_reason(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    live._CACHE.clear()
    baseline = live.evaluate_live_decision(_state())

    state = _state()
    state["source_status"]["forecast"] = "ready"
    state["forecast"] = {
        "source": "kronos",
        "asof_utc": "2026-09-20T18:00:00Z",
        "direction": "short",
        "horizon": "next_session",
        "point_pct": -0.72,
        "interval_80": [-1.4, -0.1],
        "confidence_kind": "ordinal_score",
        "confidence_score": 0.81,
        "confidence_label": "high",
        "selective_actionable": True,
        "provenance": {"raw_source": "Kronos/forecast_calibrated.py"},
        "calibrated_probability": 0.99,
    }
    result = live.evaluate_live_decision(state)

    assert result["forecast_evidence"]["status"] == "ready"
    assert result["forecast_evidence"]["available"] is True
    assert result["forecast_evidence"]["direction"] == "short"
    assert result["forecast_evidence"]["conflict_with_action"] is True
    assert result["action"] == baseline["action"] == "buy"
    assert result["probabilities"] == baseline["probabilities"]
    assert result["brain"] == baseline["brain"]
    assert result["blockers"] == baseline["blockers"]
    assert result["decision_authorized"] is False
    assert any(
        "Kronos next-session research forecast conflicts" in reason
        for reason in result["risk_assessment"]["reasons"]
    )
    assert "calibrated_probability" not in json.dumps(result)


def test_closed_gate_keeps_buy_and_sets_keep_out(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")

    result = live.evaluate_live_decision(_state(may_enter=False))

    assert result["lean"] == "bullish"
    assert result["raw_action"] == "buy"
    assert result["action"] == "buy"
    assert result["action"] != "wait"
    assert result["risk_assessment"]["keep_out"] is True
    assert "Entries closed" in result["blockers"]
    assert "Entries closed" in result["risk_assessment"]["reasons"]
    assert result["decision_authorized"] is False


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
        "lean": {
            "type": "choice",
            "choice": "bearish",
            "confidence": 0.8,
            "probabilities": {"bearish": 0.8, "bullish": 0.2},
        },
        "vpa_direction": {
            "type": "choice",
            "choice": "sell",
            "confidence": 0.72,
            "probabilities": {"buy": 0.28, "sell": 0.72},
        },
        "vpa_claim_support": {"type": "score", "score": 2.4, "confidence": 0.6},
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
    assert "wait" not in result["probabilities"]
    assert set(result["probabilities"]) == {"buy", "sell"}
    assert result["vpa_judgment"]["direction"] == "sell"
    assert result["vpa_judgment"]["claim_support"]["score"] == pytest.approx(2.4)


def test_parsed_answers_without_wait_key_still_work(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    answers = {
        "action": {
            "type": "choice",
            "choice": "buy",
            "confidence": 0.7,
            "probabilities": {"buy": 0.7, "sell": 0.3},
        },
        "setup": {"type": "choice", "choice": "trend_continuation", "confidence": 0.6},
        "alignment": {"type": "score", "score": 2.8, "confidence": 0.7},
        "timing": {"type": "score", "score": 2.5, "confidence": 0.7},
        "risk": {"type": "score", "score": 1.8, "confidence": 0.6},
    }
    monkeypatch.setattr(live, "_call_typesafe", lambda payload, key: (answers, "jev-test", 9))

    result = live.evaluate_live_decision(_state())

    assert result["action"] == "buy"
    assert "wait" not in result["probabilities"]
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
        assert result["action"] in {"buy", "sell"}
        assert result["action"] != "wait"
        assert result["risk_assessment"]["keep_out"] is True


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


def test_closed_gate_preserves_directional_lean_and_action(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = live.evaluate_live_decision(_state(may_enter=False))
    assert result["action"] == "buy"
    assert result["lean"] == "bullish"
    assert result["risk_assessment"]["keep_out"] is True


def test_vpa_disagreement_is_risk_not_a_wait(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    answers = {
        "action": {
            "type": "choice",
            "choice": "buy",
            "confidence": 0.8,
            "probabilities": {"buy": 0.8, "sell": 0.2},
        },
        "setup": {"type": "choice", "choice": "trend_continuation", "confidence": 0.6},
        "alignment": {"type": "score", "score": 3.0, "confidence": 0.7},
        "timing": {"type": "score", "score": 2.5, "confidence": 0.7},
        "risk": {"type": "score", "score": 1.5, "confidence": 0.6},
        "vpa_direction": {
            "type": "choice",
            "choice": "sell",
            "confidence": 0.7,
            "probabilities": {"buy": 0.3, "sell": 0.7},
        },
        "vpa_claim_support": {"type": "score", "score": 0.8, "confidence": 0.5},
    }
    monkeypatch.setattr(live, "_call_typesafe", lambda payload, key: (answers, "jev-test", 11))

    result = live.evaluate_live_decision(_state())

    assert result["action"] == "buy"
    assert result["action"] != "wait"
    assert result["vpa_judgment"]["direction"] == "sell"
    reasons = result["risk_assessment"]["reasons"]
    assert any("weakly supported" in reason for reason in reasons)
    assert any("VPA next action is sell" in reason for reason in reasons)


def test_missing_sources_do_not_create_fallback_lean(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    state = _state()
    state["source_status"] = {}
    result = live.evaluate_live_decision(state)
    assert result["lean"] == "unknown"
    assert result["action"] in {"buy", "sell"}
    assert result["action"] != "wait"
    assert "wait" not in result["probabilities"]
    assert result["risk_assessment"]["keep_out"] is True
    assert result["risk_assessment"]["label"] in {"HIGH", "EXTREME"}
    assert result["risk"]["score"] >= 2.5
    assert result["vpa_judgment"]["claim_support"]["score"] < 1.5


def test_provider_confidence_is_capped_when_lenses_are_unavailable(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    state = _state()
    state["source_status"] = {
        "options": "missing",
        "regime": "pending",
        "microstructure": "error",
        "vpa": "ready",
        "execution_gate": "ready",
    }
    answers = live._local_judgments(state)
    answers["action"] = {
        "choice": "sell",
        "confidence": 1.0,
        "probabilities": {"buy": 0.0, "sell": 1.0},
    }
    monkeypatch.setattr(live, "_call_typesafe", lambda payload, key: (answers, "jev-test", 11))

    result = live.evaluate_live_decision(state)

    assert result["action"] == "sell"
    assert result["confidence"] <= 0.52
    assert result["probabilities"] == {"buy": 0.48, "sell": 0.52}
    assert any("Only 1 of 4 decision lenses" in blocker for blocker in result["blockers"])
    assert any("certainty is capped" in blocker for blocker in result["blockers"])


def test_multi_model_confluence_elevates_confidence_and_stability(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    state = _state()
    state["options"]["signed_flow_imbalance"] = 0.28
    state["regime"]["probabilities"] = {"bullish": 0.75, "bearish": 0.12, "neutral": 0.13}
    result = live.evaluate_live_decision(state)

    assert result["action"] == "buy"
    assert result["confidence"] >= 0.70
    assert result["brain"]["confluence"] == "HIGH"
    assert result["brain"]["agreeing_models"] >= 3
    assert result["brain"]["models"]["options_flow"]["signal"] == "bullish"
    assert result["brain"]["models"]["regime"]["signal"] == "bullish"


def test_bearish_model_confluence_surfaces_confident_sell(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    state = _state()
    state["options"]["activity_lean"] = "bearish"
    state["options"]["signed_flow_imbalance"] = -0.35
    state["regime"]["primary"] = "bear_trend"
    state["regime"]["probabilities"] = {"bullish": 0.10, "bearish": 0.80, "neutral": 0.10}
    state["microstructure"]["dealer_hedging_action"] = "accelerating_down"
    state["vpa"]["bias"] = "SHORT"
    state["vpa"]["market_phase"] = "markdown"
    result = live.evaluate_live_decision(state)

    assert result["action"] == "sell"
    assert result["confidence"] >= 0.75
    assert result["brain"]["confluence"] == "HIGH"
    assert result["brain"]["agreeing_models"] >= 3
    assert result["brain"]["models"]["regime"]["signal"] == "bearish"


def test_brain_synthesis_reconciles_conflicting_signals_without_oscillation(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    state = _state()
    # Flow slightly positive but within deadband, chop regime, neutral VPA
    state["options"]["signed_flow_imbalance"] = 0.04
    state["options"]["activity_lean"] = "mixed"
    state["regime"]["primary"] = "chop"
    state["regime"]["probabilities"] = {"bullish": 0.35, "bearish": 0.32, "neutral": 0.33}
    state["vpa"]["bias"] = "NEUTRAL"
    state["vpa"]["market_phase"] = "consolidation"
    result = live.evaluate_live_decision(state)

    assert result["brain"]["confluence"] == "BALANCED"
    assert 0.50 <= result["confidence"] <= 0.55
    assert result["risk_assessment"]["keep_out"] is True


def test_brain_jitter_shield_suppresses_micro_oscillation_flips(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    # Base state with quiet market chop
    base = _state()
    base["regime"]["primary"] = "chop"
    base["regime"]["probabilities"] = {"bullish": 0.40, "bearish": 0.40, "neutral": 0.20}
    base["microstructure"]["dealer_hedging_action"] = "neutral"
    base["microstructure"]["regime"] = "positive_gamma"
    base["vpa"]["bias"] = "NEUTRAL"
    base["vpa"]["market_phase"] = "consolidation"

    actions = []
    confidences = []
    # Test a sequence of micro flow fluctuations around neutral
    for flow_val in [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]:
        s = live._compact_state(base)
        s["options"]["signed_flow_imbalance"] = flow_val
        res = live.evaluate_live_decision(s)
        actions.append(res["action"])
        confidences.append(res["confidence"])
        assert 0.50 <= res["confidence"] <= 0.55
        assert res["brain"]["stabilized"] is True

    # A quiet deadband must communicate coin-flip uncertainty, not manufacture
    # a 60% confidence floor.
    assert all(0.50 <= c <= 0.55 for c in confidences)


def test_previous_decision_suppresses_unconfirmed_flip(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    state = _state()
    state["options"]["signed_flow_imbalance"] = -0.08
    state["regime"]["primary"] = "chop"
    state["vpa"]["bias"] = "NEUTRAL"
    state["vpa"]["market_phase"] = "consolidation"
    state["previous_decision"] = {
        "action": "buy",
        "consensus_score": 0.12,
        "decided_at": "2026-09-20T17:00:00Z",
    }

    result = live.evaluate_live_decision(state)

    assert result["action"] == "buy"
    assert result["stability"]["flip_suppressed"] is True
    assert result["stability"]["proposed_action"] == "sell"
    assert result["confidence"] <= 0.52
    assert result["risk_assessment"]["keep_out"] is True


def test_closed_session_locks_previous_direction(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_CACHE_TTL_S", "0")
    state = _state(may_enter=False)
    state["execution_gate"]["must_be_flat"] = True
    state["previous_decision"] = {
        "action": "sell",
        "consensus_score": -0.4,
        "decided_at": "2026-09-20T20:00:00Z",
    }

    result = live.evaluate_live_decision(state)

    assert result["raw_action"] == "buy"
    assert result["action"] == "sell"
    assert result["stability"]["session_locked"] is True
    assert result["stability"]["flip_suppressed"] is True
    assert "after-close" in result["stability"]["reason"]
