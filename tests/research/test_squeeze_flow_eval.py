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


def test_insufficient_dates_reports_structured_not_evaluable_with_counts():
    """A panel too short for the configured walk-forward geometry must say
    so explicitly -- with the actual vs required date counts and the
    geometry that made it infeasible -- rather than silently returning a
    zeros-filled block that reads like a completed, clean evaluation.

    This reproduces the production shape: 10 unique asof dates is short of
    what the *default* geometry needs (20 initial-train + embargo + a
    validation tail), the same way an 8-usable-date panel with
    initial/validation=2/2, embargo=1 needed >=8 dates and got exactly 8 in
    runs/squeeze_validation/panel.parquet.
    """
    panel = make_deterministic_panel(n_dates=10)
    cfg = SqueezeFlowEvalConfig()  # default geometry needs far more than 10 dates
    metrics = evaluate_train_oos(panel, cfg=cfg)

    assert metrics["n_folds"] == 0
    assert metrics["status"] == "insufficient_dates"
    assert metrics["note"] == "not_enough_dates_for_walk_forward"  # kept for compatibility
    assert metrics["n_dates_available"] == int(panel["asof"].nunique()) == 10
    assert metrics["n_dates_required"] > metrics["n_dates_available"]

    geometry = metrics["geometry"]
    assert geometry["initial_train_dates"] == cfg.initial_train_dates
    assert geometry["validation_dates"] == cfg.validation_dates
    assert geometry["embargo_dates"] == cfg.embargo_dates
    assert geometry["min_partial_validation_dates"] == cfg.min_partial_validation_dates
    # The purge width the splitter actually used (SCORE_LABEL_HORIZON), not
    # the unused cfg.label_horizon (5 by default) -- see
    # test_geometry_pins_to_scored_horizon_not_cfg_label_horizon below.
    assert geometry["label_horizon"] == 1

    for name in ("train", "oos"):
        block = metrics[name]
        assert block["n"] == 0
        assert block["hit_rate"] is None
        assert block["status"] == "insufficient_dates"


def test_status_field_distinguishes_evaluated_from_never_evaluated():
    """A downstream promotion gate must be able to tell "evaluated, no
    fold could form" apart from "evaluated and scored" without inferring it
    from n==0/hit_rate==None alone, since both look identical on those two
    fields."""
    empty_metrics = evaluate_train_oos(make_deterministic_panel(n_dates=48).iloc[0:0])
    assert empty_metrics["status"] == "empty_panel"
    for name in ("train", "oos"):
        assert empty_metrics[name]["status"] == "empty_panel"
        assert empty_metrics[name]["n"] == 0
        assert empty_metrics[name]["hit_rate"] is None

    too_short_metrics = evaluate_train_oos(make_deterministic_panel(n_dates=10))
    assert too_short_metrics["status"] == "insufficient_dates"

    evaluated_metrics = evaluate_train_oos(make_deterministic_panel(n_dates=48))
    assert evaluated_metrics["status"] == "evaluated"
    assert evaluated_metrics["train"]["status"] == "evaluated"
    assert evaluated_metrics["oos"]["status"] == "evaluated"


def test_geometry_pins_to_scored_horizon_not_cfg_label_horizon():
    """`cfg.label_horizon` used to be threaded straight into the walk-forward
    purge geometry even though scoring is hardcoded to `fwd_1d` -- so a
    caller requesting `label_horizon=5` (as squeeze_validation.py does)
    silently over-purged relative to what was actually being scored,
    burning trailing dates a 1-day label never needed protected. The
    splitter must always be fed the horizon that matches the scored column
    (1), regardless of what `cfg.label_horizon` says.
    """
    panel = make_deterministic_panel(n_dates=48)
    inflated = SqueezeFlowEvalConfig(label_horizon=5)
    pinned = SqueezeFlowEvalConfig(label_horizon=1)
    metrics_inflated = evaluate_train_oos(panel, cfg=inflated)
    metrics_pinned = evaluate_train_oos(panel, cfg=pinned)

    assert metrics_inflated["status"] == "evaluated"
    # The reported label_horizon reflects what the splitter actually used,
    # not whatever cfg.label_horizon was configured to.
    assert metrics_inflated["label_horizon"] == 1
    assert metrics_pinned["label_horizon"] == 1
    # Changing cfg.label_horizon alone must not move the fold geometry at
    # all now that it is no longer threaded into the splitter call.
    assert metrics_inflated["train_dates"] == metrics_pinned["train_dates"]
    assert metrics_inflated["oos_dates"] == metrics_pinned["oos_dates"]
    assert metrics_inflated["n_folds"] == metrics_pinned["n_folds"]
