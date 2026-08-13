"""Train vs OOS evaluation of shipped squeeze + flow-shift scores."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from edge.research.panel_splits import expanding_panel_walk_forward_splits
from edge.research.squeeze_flow_eval import (
    SqueezeFlowEvalConfig,
    evaluate_train_oos,
    fit_fire_threshold,
    make_deterministic_panel,
    run_and_save,
)


def test_walk_forward_train_origins_cannot_see_oos_labels():
    panel = make_deterministic_panel()
    cfg = SqueezeFlowEvalConfig()
    metrics = evaluate_train_oos(panel, cfg=cfg)
    assert metrics["n_folds"] >= 1
    train_last = pd.Timestamp(metrics["train"]["max_asof"])
    oos_first = pd.Timestamp(metrics["oos"]["min_asof"])
    assert train_last < oos_first
    # Same geometry the shipped splitter promises: last train origin plus
    # label horizon plus embargo is strictly before the first OOS date.
    folds = list(
        expanding_panel_walk_forward_splits(
            panel,
            label_horizon=cfg.label_horizon,
            initial_train_dates=cfg.initial_train_dates,
            validation_dates=cfg.validation_dates,
            step_dates=cfg.step_dates,
            embargo_dates=cfg.embargo_dates,
            include_partial_final=cfg.include_partial_final,
            min_partial_validation_dates=cfg.min_partial_validation_dates,
            date_level="asof",
        )
    )
    fold = folds[-1]
    unique = pd.DatetimeIndex(sorted(panel["asof"].unique()))
    train_loc = unique.get_loc(fold.train_dates[-1])
    oos_loc = unique.get_loc(fold.validation_dates[0])
    assert train_loc + fold.label_horizon + fold.embargo < oos_loc


def test_train_and_oos_are_separate_blocks_with_n_and_accuracy():
    metrics = evaluate_train_oos(make_deterministic_panel())
    for name in ("train", "oos"):
        block = metrics[name]
        assert name not in ("", None)
        assert "n" in block
        assert isinstance(block["n"], int)
        assert "hit_rate" in block
        assert "rank_ic" in block
        if block["n"] > 0:
            assert block["hit_rate"] is None or (0.0 <= float(block["hit_rate"]) <= 1.0)
        bands = block["by_confidence"]
        assert "high" in bands and "low" in bands
        assert bands["high"] is not bands["low"]
        assert "n" in bands["high"] and "n" in bands["low"]


def test_threshold_is_fit_on_train_only():
    panel = make_deterministic_panel()
    metrics = evaluate_train_oos(panel)
    train = panel[panel["asof"] <= pd.Timestamp(metrics["train"]["max_asof"])]
    expected = fit_fire_threshold(train["eval_score"], train["fwd_1d"])
    # Re-fitting on the reported train window must recover the same threshold;
    # the test does not pin a numeric hit rate.
    assert metrics["chosen_threshold"] == expected
    assert metrics["oos"]["threshold"] == metrics["chosen_threshold"]


def test_run_and_save_twice_agrees_on_train_oos_numbers(tmp_path: Path):
    panel = make_deterministic_panel()
    fixture = tmp_path / "panel.parquet"
    panel.to_parquet(fixture, index=False)
    payloads = []
    for i in range(2):
        cfg = SqueezeFlowEvalConfig(
            panel_path=str(fixture),
            out_dir=str(tmp_path / f"run{i}"),
            use_fixture=False,
        )
        payloads.append(run_and_save(cfg))
    a, b = payloads
    assert a["n_rows"] == b["n_rows"] > 0
    for key in ("n", "hits", "hit_rate", "rank_ic", "threshold"):
        assert a["train"][key] == b["train"][key]
        assert a["oos"][key] == b["oos"][key]
    assert a["chosen_threshold"] == b["chosen_threshold"]
    assert a["train"]["n"] != a["oos"]["n"] or a["train"]["max_asof"] != a["oos"]["min_asof"]
