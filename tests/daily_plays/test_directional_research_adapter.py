from datetime import datetime, timezone
import base64
import json

import numpy as np
import pandas as pd

from edge.daily_plays.adapters.directional_research import (
    ARTIFACT_SCHEMA,
    FrozenDirectionalResearchAdapter,
)
from edge.daily_plays.clock import RunContext
from edge.research.challengers import FixedMenuXGBoostChallenger
from edge.research.features import feature_columns


ASOF = datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc)


def _candles():
    index = pd.date_range("2026-05-01", periods=65, freq="B", tz="UTC")
    close = np.linspace(100.0, 132.0, len(index))
    # A pure arithmetic ramp makes volume_z_20d exactly constant under any
    # fixed-length rolling window (the z-score of the endpoint of an
    # evenly-spaced window is a fixed number) -- a real zero-variance column,
    # caught by features.assert_no_degenerate_feature_columns. The wiggle below
    # breaks that linearity. Matches the same fix in
    # edge/tests/research/test_research_runner.py.
    steps = np.arange(len(index))
    volume = np.linspace(1_000_000, 1_500_000, len(index)) + 25_000 * np.sin(steps / 5)
    return pd.DataFrame(
        {
            "open": close - 0.4,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


def _artifact():
    return {
        "schema_version": ARTIFACT_SCHEMA,
        "experiment_id": "frozen-test",
        "status": "FROZEN_RESEARCH_CHALLENGER",
        "shadow_only": True,
        "broker_authorized": False,
        "underlying_gate": "PENDING_UNTOUCHED_HOLDOUT",
        "option_shadow_collection_authorized": False,
        "training_asof": "2026-07-10",
        "terminal_holdout": {
            "status": "SEALED_UNEVALUATED",
            "end": "2027-01-29",
        },
        "horizons": {
            str(horizon): {
                "horizon_days": horizon,
                "model": {
                    "type": "momentum",
                    "score_feature": f"momentum_{horizon}d",
                },
                "calibration": {
                    "coefficient": 2.0,
                    "intercept": 0.0,
                    "version": f"cal-{horizon}",
                },
                "threshold": 0.5,
                "probability_target": "underlying_directional_return_next_open_to_horizon_close",
                "development_metrics": {"expected_calibration_error": 0.02},
            }
            for horizon in (5, 10, 20)
        },
    }


def test_frozen_research_adapter_ranks_but_never_marks_a_play():
    adapter = FrozenDirectionalResearchAdapter(
        artifact_loader=_artifact,
        candle_fetcher=lambda *_args, **_kwargs: _candles(),
    )
    rows = adapter(
        context=RunContext.create(asof_utc=ASOF),
        symbols=["NVDA"],
        symbol_context={"NVDA": {"sector_etf": "XLK", "flow_direction": "in"}},
    )
    assert len(rows) == 3
    assert all(row["state"] == "RESEARCH_ONLY" for row in rows)
    assert all(row["eligible_for_play"] is False for row in rows)
    assert all(row["blocker"] == "terminal_holdout_sealed_until_2027-01-29" for row in rows)
    assert rows[0]["rank_score"] >= rows[-1]["rank_score"]
    assert rows[0]["sector_flow"]["sector_etf"] == "XLK"
    assert adapter.last_warnings == []


def test_research_adapter_fails_closed_when_artifact_is_not_sealed():
    artifact = _artifact()
    artifact["terminal_holdout"]["status"] = "OPENED"
    adapter = FrozenDirectionalResearchAdapter(
        artifact_loader=lambda: artifact,
        candle_fetcher=lambda *_args, **_kwargs: _candles(),
    )
    assert adapter(context=RunContext.create(asof_utc=ASOF), symbols=["NVDA"]) == []
    assert adapter.last_warnings == ["directional_research_artifact_not_shadow_eligible"]


def test_research_only_board_keeps_serialized_cpu_xgboost_horizon_visible():
    names = feature_columns()
    index = pd.bdate_range("2025-01-02", periods=48)
    train = pd.DataFrame({name: np.linspace(-1, 1, len(index)) + idx for idx, name in enumerate(names)}, index=index)
    labels = pd.Series(np.tile([0, 1], len(index) // 2), index=index)
    fitted = FixedMenuXGBoostChallenger(feature_names=names).fit(train, labels)
    artifact = _artifact()
    artifact["horizons"]["10"]["model"] = {
        "type": "cpu_xgboost",
        "features": list(names),
        "booster_format": "xgboost-json-base64",
        "booster_bytes_base64": base64.b64encode(bytes(fitted.estimator_.get_booster().save_raw(raw_format="json"))).decode("ascii"),
        "booster_config": {},
    }
    adapter = FrozenDirectionalResearchAdapter(
        artifact_loader=lambda: artifact,
        candle_fetcher=lambda *_args, **_kwargs: _candles(),
    )
    rows = adapter(context=RunContext.create(asof_utc=ASOF), symbols=["NVDA"])
    xgb = next(row for row in rows if row["horizon_days"] == 10)
    assert xgb["state"] == "RESEARCH_ONLY"
    assert xgb["eligible_for_play"] is False
    assert xgb["calibration_version"] == "cal-10"
    assert adapter.last_warnings == []


def test_empty_routed_symbols_generate_chain_free_rows_from_frozen_local_universe(tmp_path):
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps({"symbols": ["NVDA"]}), encoding="utf-8")
    _candles().to_parquet(tmp_path / "NVDA.parquet")
    adapter = FrozenDirectionalResearchAdapter(
        artifact_loader=_artifact,
        universe_path=universe,
        data_path=tmp_path,
        candidate_limit=1,
    )
    rows = adapter(context=RunContext.create(asof_utc=ASOF), symbols=[])
    assert len(rows) == 3
    assert {row["symbol"] for row in rows} == {"NVDA"}
    assert all(row["state"] == "RESEARCH_ONLY" and row["eligible_for_play"] is False for row in rows)
    assert adapter.last_warnings == []


def _sector_artifact():
    artifact = _artifact()
    artifact["horizons"]["20"]["model"] = {
        "type": "fixed_feature_score",
        "score_feature": "sector_residual_score_20d",
        "eligibility_feature": "sector_residual_eligible_20d",
        "hypothesis": "sector_residual_volatility_scaled_momentum",
    }
    return artifact


def test_fixed_shock_reversal_horizon_receives_latest_causal_shock_features():
    artifact = _artifact()
    artifact["horizons"]["5"]["model"] = {
        "type": "fixed_feature_score",
        "score_feature": "shock_reversal_score_5d",
        "eligibility_feature": "shock_reversal_eligible_5d",
        "hypothesis": "volatility_normalized_one_day_shock_reversal",
    }
    adapter = FrozenDirectionalResearchAdapter(artifact_loader=lambda: artifact,
                                               candle_fetcher=lambda *_args, **_kwargs: _candles())
    rows = adapter(context=RunContext.create(asof_utc=ASOF), symbols=["NVDA"])
    shock = next(row for row in rows if row["horizon_days"] == 5)
    assert isinstance(shock["research_signal_eligible"], bool)
    assert shock["state"] == "RESEARCH_ONLY"
    assert adapter.last_warnings == []


def test_fixed_sector_residual_uses_local_leave_one_out_peer_features(tmp_path):
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps({"symbols": ["NVDA", "AMD"], "sectors": {"semis": ["NVDA", "AMD"]}}), encoding="utf-8")
    nvda = _candles()
    amd = _candles().copy()
    close = np.linspace(100.0, 170.0, len(amd)) ** 1.01
    amd.loc[:, "close"] = close
    amd.loc[:, "open"] = close - .4
    amd.loc[:, "high"] = close + 1
    amd.loc[:, "low"] = close - 1
    nvda.to_parquet(tmp_path / "NVDA.parquet")
    amd.to_parquet(tmp_path / "AMD.parquet")
    adapter = FrozenDirectionalResearchAdapter(artifact_loader=_sector_artifact, universe_path=universe, data_path=tmp_path)
    rows = adapter(context=RunContext.create(asof_utc=ASOF), symbols=["NVDA"])
    sector = next(row for row in rows if row["horizon_days"] == 20)
    assert sector["research_signal_eligible"] is True
    assert sector["side"] in {"long", "short"}
    assert sector["state"] == "RESEARCH_ONLY" and sector["eligible_for_play"] is False
    assert adapter.last_warnings == []


def test_fixed_sector_residual_abstains_without_a_local_peer_instead_of_using_momentum(tmp_path):
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps({"symbols": ["NVDA"], "sectors": {"semis": ["NVDA"]}}), encoding="utf-8")
    _candles().to_parquet(tmp_path / "NVDA.parquet")
    adapter = FrozenDirectionalResearchAdapter(artifact_loader=_sector_artifact, universe_path=universe, data_path=tmp_path)
    rows = adapter(context=RunContext.create(asof_utc=ASOF), symbols=["NVDA"])
    sector = next(row for row in rows if row["horizon_days"] == 20)
    assert sector["research_signal_eligible"] is False
    assert sector["side"] == "neutral"
    assert sector["rank_score"] == 0.0
