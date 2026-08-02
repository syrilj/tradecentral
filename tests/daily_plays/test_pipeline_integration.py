"""Offline replay coverage for the complete daily decision-support path."""
from datetime import datetime, timezone
import json

from edge.daily_plays.adapters.flow import normalize_flow_payload
from edge.daily_plays.adapters.internal_models import normalize_internal_model_payload
from edge.daily_plays.adapters.kronos import normalize_kronos_payload
from edge.daily_plays.clock import RunContext
from edge.daily_plays.config import load_config
from edge.daily_plays.contracts import RunMode, canonical_json
from edge.daily_plays.pipeline import PipelineAdapters, run_pipeline

ASOF = datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc)


def _internal():
    return normalize_internal_model_payload({"symbol":"NVDA", "live":{"go_long":True}, "model":{"setup_ok":True},
        "confidence":{"calibrated_probability":.71, "calibration_version":"v90-cal-1",
                      "probability_target":"underlying_directional_return", "horizon_days":10,
                      "entry_threshold":.65, "threshold_version":"v90-gate-1",
                      "model_artifact_sha256":"a" * 64, "promotion_authorized":True}})


def _snapshot(**contract):
    # Explicitly meets the frozen shadow policy (30-60 DTE, delta band,
    # liquidity, IV, and a one-contract premium below the 0.5% risk limit).
    leg = {"underlying":"NVDA", "right":"call", "expiry":"2026-09-18", "dte":50, "strike":180,
           "occ_symbol":"NVDA260918C00180000", "bid":.039, "ask":.04, "mid":.0395, "spread_pct":.025,
           "volume":50, "open_interest":500, "delta":.5, "gamma":.02, "iv":.4,
           "quote_asof_utc":"2026-07-30T14:04:50Z", "provider":"lse", "multiplier":100,
           "adjusted":False}
    leg.update(contract)
    return {"symbol":"NVDA", "provider":"lse", "degraded":False, "asof_utc":"2026-07-30T14:04:50Z",
            "underlying":{"symbol":"NVDA", "price":175, "quote_asof_utc":"2026-07-30T14:04:50Z"}, "contracts":[leg]}


class Provider:
    def __init__(self, snapshot=None, error=False): self._snapshot, self.error = snapshot, error
    def snapshot(self, symbol, *, asof_utc=None):
        if self.error: raise TimeoutError("fixture provider timeout")
        return self._snapshot


def _run(tmp_path, provider, *, internal=None, mode=RunMode.REPLAY):
    adapters = PipelineAdapters(internal_models=lambda **_: [_internal()] if internal is None else internal,
        kronos=lambda *_, **__: {"direction":"long"}, flow=lambda *_, **__: {"direction":"long"}, options=provider)
    return run_pipeline(context=RunContext.create(asof_utc=ASOF, mode=mode), account=1000, config=load_config(), adapters=adapters, output_root=tmp_path)


def test_replay_fresh_calibrated_lse_fixture_is_the_only_enter_path_and_persists(tmp_path):
    result = _run(tmp_path, Provider(_snapshot()))
    assert result["plays"][0]["state"] == "ENTER"
    assert result["plays"][0]["legs"][0]["occ_symbol"] == "NVDA260918C00180000"
    assert result["plays"][0]["confidence"]["probability_target"] == "underlying_directional_return"
    assert result["plays"][0]["confidence"]["horizon_days"] == 10
    assert result["plays"][0]["provenance"]["shadow_only"] is True
    assert "NaN" not in canonical_json(result) and "Infinity" not in canonical_json(result)
    root = tmp_path / result["run_id"]
    assert {x.name for x in root.iterdir()} == {
        "manifest.json", "candidates.json", "option_snapshots.json",
        "plays.json", "decisions.json", "discovery.json",
        "flow_activity.json", "research_board.json",
    }
    assert json.loads((root / "research_board.json").read_text()) == []
    _run(tmp_path, Provider(_snapshot()))
    assert len((tmp_path / "shadow_decisions.jsonl").read_text().splitlines()) == 1


def test_research_board_persists_separately_and_never_enters_shadow_ledger(tmp_path):
    research_rows = [
        {"symbol": "AAA", "rank_score": 0.9, "research_only": True},
        {"symbol": "ZZZ", "rank_score": 0.1, "research_only": True},
    ]
    result = run_pipeline(
        context=RunContext.create(asof_utc=ASOF, mode=RunMode.REPLAY),
        account=1000,
        config=load_config(),
        output_root=tmp_path,
        adapters=PipelineAdapters(
            internal_models=lambda **_: [_internal()],
            research_models=lambda **_: research_rows,
            options=Provider(_snapshot()),
        ),
    )
    root = tmp_path / result["run_id"]
    assert json.loads((root / "research_board.json").read_text()) == research_rows
    ledger_entry = json.loads((tmp_path / "shadow_decisions.jsonl").read_text())
    assert "research_board" not in ledger_entry
    assert ledger_entry["plays"] == json.loads((root / "decisions.json").read_text())


def test_replay_ordinal_stale_failure_and_no_play_fail_closed(tmp_path):
    ordinal = _internal(); ordinal["model"]["confidence_kind"] = "ordinal_score"; ordinal["model"]["probability"] = None
    watch = _run(tmp_path, Provider(_snapshot()), internal=[ordinal])
    assert watch["plays"] == []
    assert watch["watchlist"][0]["state"] == "WATCH"
    stale = _run(tmp_path, Provider(_snapshot(quote_asof_utc="2026-07-30T14:00:00Z")))
    assert stale["plays"] == []
    assert stale["rejections"][0]["state"] == "ABSTAIN"
    assert "stale_quote" in stale["rejections"][0]["confidence"]["failed_checks"]
    no_play = _run(tmp_path, Provider(_snapshot()), internal=[])
    assert no_play["plays"] == [] and no_play["status"] == "NO_PLAY"


def test_legacy_probability_without_target_semantics_cannot_enter(tmp_path):
    legacy = _internal()
    legacy["model"]["probability_target"] = None
    legacy["model"]["horizon_days"] = None
    result = _run(tmp_path, Provider(_snapshot()), internal=[legacy])
    assert result["plays"] == []
    assert result["watchlist"][0]["state"] == "WATCH"
    assert "calibrated_probability_target_semantics_missing" in result["watchlist"][0]["confidence"]["reasons"]


def test_probability_below_artifact_threshold_cannot_request_chain_or_enter(tmp_path):
    calls = []
    below = _internal()
    below["model"]["probability"] = .64
    result = _run(
        tmp_path,
        Provider(_snapshot()),
        internal=[below],
    )
    assert result["plays"] == []
    assert result["watchlist"][0]["state"] == "WATCH"
    assert result["scan_scope"]["chain_requests"] == 0
    assert "model_probability_below_entry_threshold" in result["watchlist"][0]["confidence"]["reasons"]


def test_live_candidate_cannot_enter_outside_regular_session(tmp_path):
    closed_asof = datetime(2026, 7, 30, 21, 5, tzinfo=timezone.utc)
    result = run_pipeline(
        context=RunContext.create(asof_utc=closed_asof, mode=RunMode.LIVE),
        account=1000,
        config=load_config(),
        adapters=PipelineAdapters(
            internal_models=lambda **_: [_internal()],
            options=Provider(_snapshot(quote_asof_utc="2026-07-30T21:04:50Z")),
        ),
        output_root=tmp_path,
    )
    assert result["plays"] == []
    assert result["scan_scope"]["chain_requests"] == 0
    assert "market_session_not_regular" in result["rejections"][0]["confidence"]["failed_checks"]


def test_provider_failure_is_degraded_abstention_not_exception(tmp_path):
    result = _run(tmp_path, Provider(error=True), mode=RunMode.LIVE)
    assert result["mode"] == "degraded"
    assert result["status"] == "NO_PLAY"
    assert result["plays"] == []
    assert result["rejections"][0]["state"] == "ABSTAIN"
    assert any("options_unavailable" in warning for warning in result["warnings"])


def test_horizon_rows_share_evidence_fetch_and_warnings_are_stably_deduped(tmp_path):
    calls = []
    rows = []
    for horizon in (5, 10, 20):
        row = _internal()
        row["model"]["horizon_days"] = horizon
        rows.append(row)
    adapters = PipelineAdapters(
        internal_models=lambda **_: rows,
        kronos=lambda symbol, **_: calls.append(("kronos", symbol)) or {"_evidence_warning": "same_warning"},
        flow=lambda symbol, **_: calls.append(("flow", symbol)) or {"_evidence_warning": "same_warning"},
        options=Provider(error=True),
    )
    result = run_pipeline(context=RunContext.create(asof_utc=ASOF), account=1000, config=load_config(),
                          adapters=adapters, output_root=tmp_path)
    assert calls == [("kronos", "NVDA"), ("flow", "NVDA")]
    assert result["warnings"].count("same_warning") == 1
    assert len([warning for warning in result["warnings"] if warning.startswith("options_unavailable:NVDA")]) == 1


def test_option_snapshots_collected_even_when_candidates_abstain(tmp_path):
    ordinal = _internal()
    ordinal["model"]["confidence_kind"] = "ordinal_score"
    ordinal["model"]["probability"] = None
    result = _run(tmp_path, Provider(_snapshot()), internal=[ordinal])
    assert result["plays"] == []
    root = tmp_path / result["run_id"]
    snapshots_data = json.loads((root / "option_snapshots.json").read_text())
    assert len(snapshots_data) == 1
    assert snapshots_data[0]["symbol"] == "NVDA"

