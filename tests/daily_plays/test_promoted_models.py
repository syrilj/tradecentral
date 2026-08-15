from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from edge.daily_plays.adapters.promoted_models import (PromotedLSEModelsAdapter, _frame,
                                                        _regular_session_hourly, resolve_promoted_model,
                                                        select_promoted_model)
from edge.daily_plays.clock import RunContext

ASOF = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)


def _universe(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(json.dumps({"symbols": ["SPY"]}))
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deployment_manifest(tmp_path, *, fallback_policy="ordered_fail_closed"):
    root = tmp_path / "TradingAlgoWork"
    models = root / "models" / "poc_va_macdha"
    active = models / "v72_dual_sleeve"
    fallback = models / "v39d_confluence"
    active.mkdir(parents=True)
    fallback.mkdir()
    (active / "signal_engine.py").write_text("ACTIVE = True\n")
    (active / "config.json").write_text("{}\n")
    (active / "results.json").write_text("{}\n")
    (fallback / "signal_engine.py").write_text("FALLBACK = True\n")
    manifest = models / "DEPLOYMENT_MANIFEST.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "active": {"equity_model": "v72_dual_sleeve", "bundle": {
            "path": "models/poc_va_macdha/v72_dual_sleeve",
            "signal_engine_sha256": _sha(active / "signal_engine.py"),
            "config_sha256": _sha(active / "config.json"),
            "results_sha256": _sha(active / "results.json"),
        }},
        "data_contract": {"universe": ["TSLA.US", "MU.US", "SPY.US", "IONQ.US", "APLD.US", "XLP.US", "QQQ.US"]},
        "rollback_model": "v39d_confluence",
        "fallbacks": {"equity": ["v39d_confluence"], "policy": fallback_policy},
    }))
    return manifest, active


def _candles():
    import pandas as pd

    rows = []
    for day in pd.bdate_range("2026-07-16", "2026-07-30"):
        for hour in range(7):
            for minute in (30, 0):
                local = pd.Timestamp(day.date(), tz="America/New_York") + pd.Timedelta(hours=9 + hour, minutes=minute)
                if local.hour == 9 and minute == 0:
                    continue
                if local.tz_convert("UTC").to_pydatetime() > ASOF:
                    continue
                price = 100 + len(rows)
                rows.append({"timestamp": local.tz_convert("UTC").isoformat(), "open": price,
                             "high": price + 1, "low": price - 1, "close": price + .5, "volume": 1000})
    return rows


def test_promoted_frame_accepts_rest_fallback_dataframe():
    import pandas as pd

    rows = _candles()
    frame = pd.DataFrame(rows).set_index("timestamp")
    normalized = _frame(frame)
    assert list(normalized.columns) == ["open", "high", "low", "close", "volume"]
    assert str(normalized.index.tz) == "UTC"
    assert len(normalized) == len(rows)


def test_production_defaults_to_v72_when_manifest_bundle_and_domain_are_valid(tmp_path):
    manifest, _ = _deployment_manifest(tmp_path)
    selection = resolve_promoted_model(manifest_path=manifest)
    assert selection.model == "v72_dual_sleeve"
    assert selection.active is True
    assert select_promoted_model(manifest_path=manifest) == "v72_dual_sleeve"


def test_tampered_active_bundle_uses_only_declared_ordered_fail_closed_fallback(tmp_path):
    manifest, active = _deployment_manifest(tmp_path)
    (active / "signal_engine.py").write_text("TAMPERED = True\n")
    selection = resolve_promoted_model(manifest_path=manifest)
    assert selection == selection.__class__("v39d_confluence", False, "manifest_active_checksum_invalid")


def test_metrics_evidence_drift_is_an_explicit_advisory_not_an_executable_failover(tmp_path):
    manifest, active = _deployment_manifest(tmp_path)
    (active / "results.json").write_text("{\"normalized\": true}\n")
    selection = resolve_promoted_model(manifest_path=manifest)
    assert selection.model == "v72_dual_sleeve"
    assert selection.active is True
    assert selection.advisories == ("manifest_results.json_checksum_invalid",)


def test_invalid_active_without_ordered_fail_closed_policy_returns_no_model(tmp_path):
    manifest, active = _deployment_manifest(tmp_path, fallback_policy="best_effort")
    (active / "signal_engine.py").write_text("TAMPERED = True\n")
    assert resolve_promoted_model(manifest_path=manifest).model is None


def test_lse_candle_request_uses_provider_symbol_and_newest_order(monkeypatch):
    import sys
    import types

    calls = {}

    class FakeClient:
        def candles(self, *args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs
            return []

    class FakeAdapter:
        def __init__(self, *, api_key):
            assert api_key == "test-key"
            self.client = FakeClient()

    fake_runtime = types.ModuleType("services.market_runtime")
    fake_runtime.LSEAdapter = FakeAdapter
    monkeypatch.setitem(sys.modules, "services.market_runtime", fake_runtime)
    monkeypatch.setenv("LSE_API_KEY", "test-key")

    from edge.daily_plays.adapters.promoted_models import _lse_candles

    _lse_candles("SPY", context=RunContext.create(asof_utc=ASOF))
    assert calls["args"][:2] == ("SPY", "30m")
    assert calls["kwargs"]["order"] == "desc"
    assert calls["kwargs"]["end"] == "2026-07-31"


def test_v71_generate_runs_on_a_copied_ohlcv_frame():
    import pandas as pd
    import pytest
    from edge.daily_plays.adapters.promoted_models import _engine

    index = pd.date_range("2025-01-01", periods=320, freq="h", tz="UTC")
    close = pd.Series(range(320), index=index, dtype=float) + 100
    frame = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                          "close": close, "volume": 1000.0}, index=index)
    try:
        engine = _engine("v71_live_confidence")
    except (PermissionError, OSError, RuntimeError):
        pytest.skip("External TradingAlgoWork directory not accessible in sandbox")
    generated = engine.generate({"AAA.US": frame.copy()})
    assert len(generated["AAA.US"]) == len(frame)
    assert len(engine.last_confidence["AAA.US"]) == len(frame)


def test_v71_probability_is_diagnostic_and_never_mislabeled_as_fixed_horizon(tmp_path):
    adapter = PromotedLSEModelsAdapter(
        universe_path=_universe(tmp_path), candle_fetcher=lambda *_a, **_kw: _candles(),
        model_runner=lambda **_kw: {"weight": 1, "raw_probability": .7, "setup_ok": True},
        calibrator_loader=lambda _m: {"available": True, "artifact": {"calibration_type": "platt"}},
        confidence_evaluator=lambda *_a, **_kw: {"state": "WATCH", "confidence_kind": "calibrated_probability",
                                                  "calibrated_probability": .72, "calibration_version": "platt-test"})
    rows = list(adapter(context=RunContext.create(asof_utc=ASOF)))
    assert len(rows) == 1
    assert rows[0]["model"]["id"] == "v71_live_confidence"
    assert rows[0]["model"]["probability"] is None
    assert rows[0]["model"]["confidence_kind"] == "ordinal_score"
    assert rows[0]["model"]["probability_target"] is None
    assert rows[0]["model"]["horizon_days"] is None
    assert rows[0]["model"]["diagnostic_probability"] == {
        "value": .72,
        "target": "strategy_trade_realized_r_positive",
        "horizon": "entry_to_strategy_exit",
        "calibration_version": "platt-test",
        "actionable": False,
    }


def test_v72_confidence_is_ordinal_diagnostic_and_never_an_options_probability(tmp_path, monkeypatch):
    import pandas as pd
    from edge.daily_plays.adapters import promoted_models

    class Engine:
        def __init__(self):
            self.last_confidence = {}

        def generate(self, data):
            self.last_confidence = {key: pd.Series(.66, index=frame.index) for key, frame in data.items()}
            return {key: pd.Series(.25, index=frame.index) for key, frame in data.items()}

    monkeypatch.setattr(promoted_models, "resolve_promoted_model",
                        lambda **_kw: promoted_models.PromotedModelSelection("v72_dual_sleeve", True))
    monkeypatch.setattr(promoted_models, "_engine", lambda _model: Engine())
    monkeypatch.setattr(promoted_models, "_source_runtime", lambda: (
        lambda *_a, **_kw: {"available": True, "stale": False, "future_timestamp": False},
        lambda *_a, **_kw: {"state": "WATCH", "confidence_kind": "calibrated_probability",
                             "calibrated_probability": .99, "calibration_version": "identity"},
        lambda _model: {"available": False, "reason": "identity"}, None,
    ))
    adapter = PromotedLSEModelsAdapter(universe_path=_universe(tmp_path), candle_fetcher=lambda *_a, **_kw: _candles())
    row = list(adapter(context=RunContext.create(asof_utc=ASOF)))[0]
    assert row["model"]["id"] == "v72_dual_sleeve"
    assert row["model"]["confidence_kind"] == "ordinal_score"
    assert row["model"]["probability"] is None
    assert row["model"]["probability_target"] is None
    assert row["model"]["horizon_days"] is None
    assert row["model"]["diagnostic_probability"] is None
    assert row["model"]["diagnostic_confidence"] == {
        "value": .66, "semantics": "ordinal_confidence_not_guaranteed_probability", "actionable": False,
    }


def test_identity_v50_never_becomes_a_calibrated_probability(tmp_path):
    adapter = PromotedLSEModelsAdapter(
        universe_path=_universe(tmp_path), candle_fetcher=lambda *_a, **_kw: _candles(),
        model_runner=lambda **_kw: {"weight": 1, "raw_probability": .99, "setup_ok": True},
        calibrator_loader=lambda _m: {"available": False, "reason": "identity"},
        confidence_evaluator=lambda *_a, **_kw: {"state": "ABSTAIN", "confidence_kind": "ordinal_confidence_score",
                                                  "calibrated_probability": .99, "uncalibrated": True})
    row = list(adapter(context=RunContext.create(asof_utc=ASOF)))[0]
    assert row["model"]["confidence_kind"] == "ordinal_score"
    assert row["model"]["probability"] is None


def test_v71_regular_session_aggregation_is_0930_aligned_and_point_in_time():
    import pandas as pd

    index = pd.DatetimeIndex(["2026-07-29 13:30Z", "2026-07-29 14:00Z", "2026-07-29 14:30Z", "2026-07-29 15:00Z"])
    frame = pd.DataFrame({"open": [10, 11, 12, 13], "high": [11, 12, 13, 14], "low": [9, 10, 11, 12],
                          "close": [10.5, 11.5, 12.5, 13.5], "volume": [2, 3, 4, 5]}, index=index)
    hourly = _regular_session_hourly(frame, asof_utc=datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc))
    assert list(hourly.index.strftime("%H:%M")) == ["13:30", "14:30"]
    assert hourly.iloc[0].to_dict() == {"open": 10, "high": 12, "low": 9, "close": 11.5, "volume": 5}


def test_future_bars_cannot_change_historical_promoted_prediction(tmp_path):
    seen = []

    def runner(**kwargs):
        seen.append(kwargs["frame"].copy())
        return {"weight": 1, "raw_probability": .7, "setup_ok": True}

    adapter = PromotedLSEModelsAdapter(
        universe_path=_universe(tmp_path), candle_fetcher=lambda *_a, **_kw: _candles(), model_runner=runner,
        calibrator_loader=lambda _m: {"available": True, "artifact": {"calibration_type": "platt"}},
        confidence_evaluator=lambda *_a, **_kw: {"confidence_kind": "calibrated_probability", "calibrated_probability": .72})
    first = list(adapter(context=RunContext.create(asof_utc=ASOF)))
    future = _candles() + [{"timestamp": "2026-07-31T13:30:00Z", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    adapter.candle_fetcher = lambda *_a, **_kw: future
    second = list(adapter(context=RunContext.create(asof_utc=ASOF)))
    assert first == second
    assert seen[0].equals(seen[1])


def test_promoted_adapter_rejects_symbols_outside_its_frozen_training_bag(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(json.dumps({"symbols": ["AAA"]}))
    adapter = PromotedLSEModelsAdapter(
        universe_path=path, candle_fetcher=lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError()),
        model_runner=lambda **_kw: {}, calibrator_loader=lambda _m: {"available": False},
        confidence_evaluator=lambda *_a, **_kw: {},
    )
    assert list(adapter(context=RunContext.create(asof_utc=ASOF))) == []
    assert adapter.last_warnings == ["unsupported_promoted_symbol:AAA"]


def test_frozen_bag_is_filtered_before_wide_universe_limit(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(json.dumps({"symbols": [*[f"BAD{i}" for i in range(30)],
                                                     "SPY", "IONQ", "APLD", "XLP"]}))
    seen = []
    adapter = PromotedLSEModelsAdapter(
        universe_path=path, candidate_limit=7,
        candle_fetcher=lambda symbol, **_kw: seen.append(symbol) or _candles(),
        model_runner=lambda **_kw: {"weight": 0, "raw_probability": .5, "setup_ok": False},
        calibrator_loader=lambda _m: {"available": False},
        confidence_evaluator=lambda *_a, **_kw: {},
    )
    list(adapter(context=RunContext.create(asof_utc=ASOF)))
    assert seen == ["SPY", "IONQ", "APLD", "XLP"]


def test_injected_provider_receives_point_in_time_end_bound(tmp_path):
    calls = []
    adapter = PromotedLSEModelsAdapter(
        universe_path=_universe(tmp_path), candle_fetcher=lambda symbol, **kwargs: calls.append(kwargs) or _candles(),
        model_runner=lambda **_kw: {"weight": 1, "raw_probability": .7},
        calibrator_loader=lambda _m: {"available": False}, confidence_evaluator=lambda *_a, **_kw: {})
    list(adapter(context=RunContext.create(asof_utc=ASOF)))
    assert calls == [{"context": RunContext.create(asof_utc=ASOF), "end_utc": ASOF}]
