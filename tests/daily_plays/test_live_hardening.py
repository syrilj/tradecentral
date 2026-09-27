from datetime import datetime, timezone
import json

from edge.daily_plays.adapters.kronos import load_point_in_time_kronos
from edge.daily_plays.adapters.options import LSEOptionsAdapter
from edge.daily_plays.clock import RunContext
from edge.daily_plays.config import load_config
from edge.daily_plays.pipeline import PipelineAdapters, empty_live_adapters, run_pipeline


ASOF = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)


def _internal(symbol="NVDA"):
    return {"symbol": symbol, "side": "long", "setup_ok": True,
            "model": {"confidence_kind": "calibrated_probability", "probability": .71,
                      "calibration_version": "test",
                      "probability_target": "underlying_directional_return",
                      "horizon_days": 10, "entry_threshold": .65,
                      "threshold_version": "test-gate-v1",
                      "artifact_sha256": "c" * 64,
                      "promotion_authorized": True}}


def _snapshot(symbol):
    return {"contracts": [{"underlying": symbol, "right": "call", "expiry": "2026-09-18", "dte": 50,
        "strike": 180, "occ_symbol": f"{symbol}260918C00180000", "bid": .039, "ask": .04,
        "volume": 50, "open_interest": 500, "delta": .5, "gamma": .02, "iv": .4,
        "quote_asof_utc": "2026-07-30T14:59:50Z", "provider": "lse",
        "multiplier": 100, "adjusted": False}]}


def test_same_session_kronos_loader_rejects_future_and_never_changes_probability(tmp_path):
    context = RunContext.create(asof_utc=ASOF)
    path = tmp_path / "LIVE_FUSION_2026-07-30.json"
    path.write_text(json.dumps({"asof": "2026-07-30 11:30", "rows": [{"ticker": "NVDA", "model": {"tmr_point_pct": .9, "conf_score": 99}}]}))
    assert load_point_in_time_kronos("NVDA", context=context, forecasts_root=tmp_path)["_evidence_warning"] == "kronos_artifact_from_future"
    path.write_text(json.dumps({"asof": "2026-07-30 09:30", "rows": [{"ticker": "NVDA", "model": {"tmr_point_pct": .9, "conf_score": 99}}]}))
    evidence = load_point_in_time_kronos("NVDA", context=context, forecasts_root=tmp_path)
    assert "calibrated_probability" not in evidence
    result = run_pipeline(context=context, account=1000, config=load_config(), persist=False,
        adapters=PipelineAdapters(internal_models=lambda **_: [_internal()], kronos=lambda *_, **__: evidence,
            options=LSEOptionsAdapter(fetcher=_snapshot)))
    assert result["candidates"][0]["confidence"]["calibrated_probability"] == .71


def test_evidence_warnings_surface_and_options_are_only_called_after_shortlist():
    calls = []
    evidence_calls = []
    provider = LSEOptionsAdapter(fetcher=lambda symbol: calls.append(symbol) or _snapshot(symbol))
    adapters = PipelineAdapters(internal_models=lambda **_: [_internal("NVDA"), _internal("AAPL")],
        kronos=lambda symbol, **_: evidence_calls.append(("kronos", symbol)) or {"_evidence_warning": "kronos_same_session_artifact_missing"},
        flow=lambda symbol, **_: evidence_calls.append(("flow", symbol)) or {"_evidence_warning": "flow_lse_credential_missing"}, options=provider)
    result = run_pipeline(context=RunContext.create(asof_utc=ASOF), account=1000, config=load_config(), adapters=adapters, persist=False)
    assert calls == ["AAPL", "NVDA"]  # only the fusion shortlist, never internal candidate generation
    assert "kronos_same_session_artifact_missing" in result["warnings"]
    assert "flow_lse_credential_missing" in result["warnings"]
    assert result["mode"] == "live"
    assert result["advisory_evidence_warnings"] == [
        "kronos_same_session_artifact_missing", "flow_lse_credential_missing",
    ]
    assert result["execution_health_warnings"] == []
    assert evidence_calls == [("kronos", "NVDA"), ("flow", "NVDA"), ("kronos", "AAPL"), ("flow", "AAPL")]


def test_research_board_is_advisory_and_never_changes_decision_or_chain_calls():
    class Research:
        last_warnings = ["research_artifact_stale"]

        def __call__(self, **_):
            return [
                {"symbol": "ZZZ", "rank_score": 0.1, "research_only": True},
                {"symbol": "AAA", "rank_score": 0.9, "research_only": True},
            ]

    baseline_calls = []
    research_calls = []
    baseline = run_pipeline(
        context=RunContext.create(asof_utc=ASOF), account=1000, config=load_config(), persist=False,
        adapters=PipelineAdapters(
            internal_models=lambda **_: [_internal()],
            options=LSEOptionsAdapter(fetcher=lambda symbol: baseline_calls.append(symbol) or _snapshot(symbol)),
        ),
    )
    with_research = run_pipeline(
        context=RunContext.create(asof_utc=ASOF), account=1000, config=load_config(), persist=False,
        adapters=PipelineAdapters(
            internal_models=lambda **_: [_internal()],
            research_models=Research(),
            options=LSEOptionsAdapter(fetcher=lambda symbol: research_calls.append(symbol) or _snapshot(symbol)),
        ),
    )
    assert (with_research["status"], with_research["mode"], with_research["decision_count"]) == (
        baseline["status"], baseline["mode"], baseline["decision_count"],
    )
    assert research_calls == baseline_calls == ["NVDA"]
    assert with_research["research_board"] == [
        {"symbol": "AAA", "rank_score": 0.9, "research_only": True},
        {"symbol": "ZZZ", "rank_score": 0.1, "research_only": True},
    ]
    assert with_research["research_board_count"] == 2
    assert with_research["advisory_evidence_warnings"] == ["research_artifact_stale"]
    assert with_research["execution_health_warnings"] == []


def test_manifest_metrics_drift_is_advisory_and_does_not_degrade_execution():
    class Model:
        last_warnings = [
            "promoted_model_manifest_advisory:manifest_results.json_checksum_invalid"
        ]

        def __call__(self, **_):
            return [_internal()]

    result = run_pipeline(
        context=RunContext.create(asof_utc=ASOF),
        account=1000,
        config=load_config(),
        persist=False,
        adapters=PipelineAdapters(
            internal_models=Model(),
            options=LSEOptionsAdapter(fetcher=_snapshot),
        ),
    )
    assert result["mode"] == "live"
    assert result["execution_health_warnings"] == []
    assert result["advisory_evidence_warnings"] == [
        "promoted_model_manifest_advisory:manifest_results.json_checksum_invalid"
    ]


def test_default_path_without_lse_key_is_degraded_and_never_enters(monkeypatch):
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    result = run_pipeline(context=RunContext.create(asof_utc=ASOF), account=1000, config=load_config(), adapters=empty_live_adapters(), persist=False)
    assert result["mode"] == "degraded"
    assert not any(play["state"] == "ENTER" for play in result["plays"])
    assert "lse_credential_missing" in result["warnings"]
    assert not any(item.startswith("options_unavailable:") for item in result["warnings"])
