import json
from pathlib import Path

from edge.daily_plays.adapters.flow import normalize_flow_payload
from edge.daily_plays.adapters.internal_models import normalize_internal_model_payload
from edge.daily_plays.adapters.kronos import normalize_kronos_payload
from edge.daily_plays.fusion import fuse_candidate, rank_candidates


FIXTURES = Path(__file__).parent / "fixtures"


def _records():
    internal = normalize_internal_model_payload(json.loads((FIXTURES / "live_plan_calibrated.json").read_text()))
    kronos = normalize_kronos_payload(json.loads((FIXTURES / "kronos_report.json").read_text()))
    flow = normalize_flow_payload(json.loads((FIXTURES / "flow_symbol.json").read_text()))
    return internal, kronos, flow


def test_kronos_cannot_increase_calibrated_probability():
    internal, kronos, flow = _records()
    fused = fuse_candidate(internal, kronos=kronos, flow=flow)
    assert fused["confidence"]["calibrated_probability"] == 0.71
    assert fused["confidence"]["calibrated_probability"] != kronos["research_confidence"]["score"]
    assert fused["state"] == "WATCH"  # execution validation remains downstream
    assert fused["confidence"]["probability_target"] is None
    assert "calibrated_probability_target_semantics_missing" in fused["confidence"]["reasons"]


def test_ordinal_confidence_cannot_emit_enter():
    internal, kronos, flow = _records()
    internal["model"].update({"confidence_kind": "ordinal_score", "probability": None})
    fused = fuse_candidate(internal, kronos=kronos, flow=flow)
    assert fused["state"] == "WATCH"
    assert "model_probability_not_calibrated" in fused["confidence"]["reasons"]


def test_ranking_is_bounded_and_deterministic():
    internal, kronos, flow = _records()
    other = {**internal, "symbol": "AAPL"}
    ranked = rank_candidates([internal, other], kronos_by_symbol={"NVDA": kronos}, flow_by_symbol={"NVDA": flow}, limit=1)
    assert [row["rank"] for row in ranked] == [1]
    assert len(ranked) == 1


def test_calibrated_underlying_probability_preserves_frozen_horizon_semantics():
    internal, kronos, flow = _records()
    internal["model"].update({"probability_target": "underlying_directional_return", "horizon_days": 10})
    fused = fuse_candidate(internal, kronos=kronos, flow=flow)
    assert fused["confidence"]["probability_target"] == "underlying_directional_return"
    assert fused["confidence"]["horizon_days"] == 10
    assert "calibrated_probability_target_semantics_missing" not in fused["confidence"]["reasons"]


def test_rank_candidates_keeps_one_deterministic_strongest_horizon_per_symbol():
    base = {
        "symbol": "NVDA", "side": "long", "setup_ok": True,
        "model": {"confidence_kind": "ordinal_score", "probability": None,
                  "probability_target": "underlying_directional_return"},
    }
    rows = [
        {**base, "model": {**base["model"], "raw_score": .8, "horizon_days": 5}},
        {**base, "model": {**base["model"], "raw_score": -1.2, "horizon_days": 10}},
        {**base, "model": {**base["model"], "raw_score": .4, "horizon_days": 20}},
        {**base, "symbol": "AAPL", "model": {**base["model"], "raw_score": .9, "horizon_days": 5}},
    ]
    ranked = rank_candidates(rows, limit=10)
    assert [row["symbol"] for row in ranked] == ["NVDA", "AAPL"]
    assert ranked[0]["confidence"]["horizon_days"] == 10
    assert ranked[0]["ranking"] == {
        "model_component": 1.2, "model_component_kind": "ordinal_strength", "ordinal_strength": 1.2,
    }
    assert ranked[0]["confidence"]["model_probability"] is None


def test_equal_ordinal_horizon_strength_prefers_shorter_frozen_horizon():
    internal = {"symbol": "NVDA", "side": "long", "setup_ok": True,
                "model": {"confidence_kind": "ordinal_score", "probability": None, "raw_score": 1.0,
                          "probability_target": "underlying_directional_return"}}
    ranked = rank_candidates([
        {**internal, "model": {**internal["model"], "horizon_days": 20}},
        {**internal, "model": {**internal["model"], "horizon_days": 5}},
    ])
    assert len(ranked) == 1
    assert ranked[0]["confidence"]["horizon_days"] == 5
