from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.challengers import FixedMenuXGBoostChallenger
from edge.research.evaluation import TrialSpec
from edge.research.runner import (ResearchProtocol, _folds, _serialize_fitted_model, code_fingerprint, dataset_fingerprint,
                                  load_universe, prepare_research_panel)


def _write(path, symbol: str, phase: float) -> None:
    dates = pd.bdate_range("2024-01-02", periods=100)
    close = 100 + np.arange(100) * .1 + np.sin(np.arange(100) / 5 + phase)
    # A pure arithmetic ramp makes volume_z_20d exactly constant under any
    # fixed-length rolling window (the z-score of the endpoint of an
    # evenly-spaced window is a fixed number) -- a real zero-variance column,
    # caught by features.assert_no_degenerate_feature_columns. The wiggle
    # below breaks the linearity the same way `close` already does above.
    volume = 1_000 + np.arange(100) + 5 * np.sin(np.arange(100) / 5 + phase)
    pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "volume": volume,
    }, index=dates).to_parquet(path / f"{symbol}.parquet")


def test_prepare_panel_is_point_in_time_and_fingerprint_is_deterministic(tmp_path):
    _write(tmp_path, "AAA", 0)
    _write(tmp_path, "BBB", 1)
    asof = "2024-04-30"
    bars, panel = prepare_research_panel(
        symbols=["AAA", "BBB"], sectors={"AAA": "one", "BBB": "two"},
        asof=asof, data_dir=tmp_path,
    )
    assert panel.index.get_level_values("timestamp").max() <= pd.Timestamp(asof)
    assert set(panel["sector"]) == {"one", "two"}
    known = panel["feature_asof"].dropna()
    assert (pd.to_datetime(known) < known.index.get_level_values("timestamp")).all()
    assert dataset_fingerprint(bars) == dataset_fingerprint(bars.copy())
    before = panel.copy()
    future = pd.read_parquet(tmp_path / "AAA.parquet")
    future.loc[future.index > asof, "close"] *= 100
    future.to_parquet(tmp_path / "AAA.parquet")
    _, after = prepare_research_panel(
        symbols=["AAA", "BBB"], sectors={"AAA": "one", "BBB": "two"},
        asof=asof, data_dir=tmp_path,
    )
    pd.testing.assert_frame_equal(before, after)


def test_checked_in_universe_has_multi_sector_mapping():
    symbols, sectors = load_universe()
    assert len(symbols) >= 40
    assert len(set(sectors.values())) >= 4


def test_cpu_xgboost_artifact_is_json_safe_and_code_fingerprint_covers_challenger():
    index = pd.bdate_range("2025-01-02", periods=60)
    features = pd.DataFrame({"f1": np.linspace(-1, 1, 60), "f2": np.cos(np.arange(60))}, index=index)
    labels = pd.Series(np.tile([0, 1], 30), index=index)
    model = FixedMenuXGBoostChallenger(feature_names=("f1", "f2")).fit(features, labels)
    spec = TrialSpec("xgb", "cpu_xgboost", {"menu_name": "conservative_v1", "config": dict(model.config)}, ("f1", "f2"))
    artifact = _serialize_fitted_model(spec, model)
    assert artifact["booster_format"] == "xgboost-json-base64"
    assert artifact["features"] == ["f1", "f2"]
    assert artifact["booster_config"]["learner"]["learner_model_param"]["num_feature"] == "2"
    assert isinstance(code_fingerprint(), str) and len(code_fingerprint()) == 64


def test_protocol_preregisters_frozen_partial_outer_validation_minimum():
    protocol = ResearchProtocol()
    assert protocol.outer_partial_final_validation is True
    assert protocol.outer_partial_validation_min_dates == 60
    with pytest.raises(ValueError, match="cannot exceed"):
        ResearchProtocol(outer_validation_dates=50, outer_partial_validation_min_dates=60)


def test_runner_uses_partial_final_outer_fold_but_keeps_inner_folds_full_sized():
    dates = pd.bdate_range("2024-01-02", periods=113)
    records = pd.DataFrame(index=pd.MultiIndex.from_product([dates, ["AAA"]], names=["timestamp", "symbol"]))
    protocol = ResearchProtocol(
        development_start=dates[0].date().isoformat(), validation_start=dates[70].date().isoformat(),
        development_end=dates[-1].date().isoformat(), terminal_holdout_start="2024-12-31",
        terminal_holdout_end="2025-06-30", outer_validation_dates=30,
        inner_initial_train_dates=20, inner_validation_dates=20,
        outer_partial_validation_min_dates=10,
    )
    folds = _folds(records, protocol, horizon_days=5)
    assert len(folds[-1].outer.validation_dates) == 13
    assert all(len(inner.validation_dates) == 20 for fold in folds for inner in fold.inner)
