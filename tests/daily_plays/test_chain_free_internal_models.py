from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

from edge.daily_plays.adapters.internal_models import ChainFreeInternalModelsAdapter
from edge.daily_plays.adapters.options import LSEOptionsAdapter
from edge.daily_plays.clock import RunContext
from edge.daily_plays.config import load_config
from edge.daily_plays.pipeline import PipelineAdapters, run_pipeline


ASOF = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)


def _candles(asof=ASOF):
    return [{"timestamp": (asof - timedelta(hours=29 - i)).isoformat(), "open": 100 + i,
             "high": 101 + i, "low": 99 + i, "close": 100.5 + i, "volume": 1000} for i in range(30)]


def _universe(tmp_path, symbols=("AAA", "BBB", "CCC")):
    path = tmp_path / "universe.json"
    path.write_text(json.dumps({"symbols": list(symbols)}))
    return path


def _platt(*_, **kwargs):
    assert kwargs["calibrator"]["artifact"]["calibration_type"] == "platt"
    return {"state": "WATCH", "confidence_kind": "calibrated_probability",
            "calibrated_probability": .71, "calibration_version": "platt-v1",
            "entry_threshold": .65, "threshold_version": "platt-gate-v1",
            "model_artifact_sha256": "b" * 64, "promotion_authorized": True,
            "reasons": []}


def _adapter(tmp_path, **extra):
    kwargs = dict(
        universe_path=_universe(tmp_path), candle_fetcher=lambda *_args, **_kw: _candles(),
        model_runner=lambda **_kw: {"weight": 1, "raw_probability": .68, "setup_ok": True},
        calibrator_loader=lambda _m: {"available": True, "artifact": {"calibration_type": "platt"}},
        confidence_evaluator=_platt)
    kwargs.update(extra)
    return ChainFreeInternalModelsAdapter(**kwargs)


def test_chain_free_generation_uses_no_options_or_gex_and_honors_active_platt(tmp_path):
    # Use the real source confidence evaluator with an injected promoted Platt
    # artifact; candidate generation has no option/GEX dependency to patch.
    adapter = ChainFreeInternalModelsAdapter(
        universe_path=_universe(tmp_path), candle_fetcher=lambda *_a, **_kw: _candles(),
        model_runner=lambda **_kw: {"weight": 1, "raw_probability": .68, "setup_ok": True},
        calibrator_loader=lambda _m: {"available": True, "path": "test-platt.json", "artifact": {
            "calibration_type": "platt", "calibrator": {"x": [0.0, 1.0], "y": [0.3, 0.9]},
            "thresholds": {"watch": .5, "enter": .6}, "version": "platt-v1"}})
    rows = list(adapter(context=RunContext.create(asof_utc=ASOF)))
    assert len(rows) == 9
    assert all(r["model"]["confidence_kind"] == "calibrated_probability" for r in rows)
    assert all(r["model"]["probability"] is not None for r in rows)
    assert {r["model"]["horizon_days"] for r in rows} == {5, 10, 20}
    assert {r["model"]["probability_target"] for r in rows} == {"underlying_directional_return"}
    # The injected candle/model seams are the only calls made before pipeline
    # shortlisting; no options/GEX adapter is supplied or reachable here.


def test_identity_calibration_is_not_promoted_to_probability(tmp_path):
    adapter = _adapter(tmp_path, calibrator_loader=lambda _m: {"available": False, "reason": "identity"},
                       confidence_evaluator=lambda *_a, **_kw: {"state": "ABSTAIN", "confidence_kind": "ordinal_confidence_score",
                                                                 "calibrated_probability": .99, "uncalibrated": True, "reasons": ["identity"]})
    row = list(adapter(context=RunContext.create(asof_utc=ASOF)))[0]
    assert row["model"]["confidence_kind"] == "ordinal_score"
    assert row["model"]["probability"] is None


def test_default_generator_reads_only_local_daily_parquet_and_is_ordinal(tmp_path):
    import pandas as pd

    data = tmp_path / "1d"
    data.mkdir()
    dates = pd.date_range("2026-02-20", periods=160, freq="D")
    close = [100 + i * .2 for i in range(len(dates))]
    pd.DataFrame({"open": close, "high": [x + 1 for x in close], "low": [x - 1 for x in close],
                  "close": close, "volume": [1000] * len(dates)}, index=dates).to_parquet(data / "AAA.parquet")
    adapter = ChainFreeInternalModelsAdapter(universe_path=_universe(tmp_path, ("AAA",)), data_path=data)
    rows = list(adapter(context=RunContext.create(asof_utc=datetime(2026, 7, 30, tzinfo=timezone.utc))))
    assert [row["model"]["horizon_days"] for row in rows] == [5, 10, 20]
    assert all(row["source"] == "local_daily_chain_free_baseline" for row in rows)
    assert all(row["model"]["confidence_kind"] == "ordinal_score" for row in rows)
    assert all(row["model"]["probability"] is None for row in rows)


def test_future_and_stale_candles_are_rejected_per_symbol(tmp_path):
    future = ChainFreeInternalModelsAdapter(universe_path=_universe(tmp_path, ("FUT",)),
        candle_fetcher=lambda *_a, **_kw: _candles(ASOF + timedelta(hours=8)), model_runner=lambda **_kw: {}, candidate_limit=1)
    stale = ChainFreeInternalModelsAdapter(universe_path=_universe(tmp_path, ("OLD",)),
        candle_fetcher=lambda *_a, **_kw: _candles(ASOF - timedelta(days=3)), model_runner=lambda **_kw: {}, candidate_limit=1)
    assert list(future(context=RunContext.create(asof_utc=ASOF))) == []
    assert "future_candle" in future.last_warnings[0]
    assert list(stale(context=RunContext.create(asof_utc=ASOF))) == []
    assert "stale_candle" in stale.last_warnings[0]


def test_weekend_and_short_holiday_like_gaps_use_business_session_age(tmp_path):
    friday = datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc)
    monday = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)
    # A Friday close is just one elapsed weekday session old on Monday, not
    # three stale calendar days.  The same conservative three-session limit
    # also tolerates a short exchange-holiday-like gap.
    adapter = ChainFreeInternalModelsAdapter(
        universe_path=_universe(tmp_path, ("WEEKEND",)),
        candle_fetcher=lambda *_a, **_kw: _candles(friday),
        model_runner=lambda **_kw: {"weight": 1}, candidate_limit=1)
    rows = list(adapter(context=RunContext.create(asof_utc=monday)))
    assert len(rows) == 3


def test_bounded_shortlist_calls_options_only_after_candidate_generation(tmp_path):
    calls = []
    adapter = _adapter(tmp_path)
    cfg = replace(load_config(), universe_path=str(adapter.universe_path), shortlist_limit=2)
    provider = LSEOptionsAdapter(fetcher=lambda symbol: calls.append(symbol) or {"contracts": []})
    result = run_pipeline(context=RunContext.create(asof_utc=ASOF), account=1000, config=cfg,
                          adapters=PipelineAdapters(internal_models=adapter, options=provider), persist=False)
    assert len(result["candidates"]) == 2
    assert len(calls) == 2
