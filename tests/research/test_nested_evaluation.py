from __future__ import annotations

import numpy as np
import pandas as pd

from edge.research.costs import UnderlyingCostModel
from edge.research.evaluation import (
    evidence_metrics,
    expected_calibration_error,
    fit_platt,
    paired_baseline_difference_metrics,
    positions_for_spec,
    positions_from_probability,
    select_threshold_for_spec,
    select_threshold,
    simple_hypothesis_trial_specs,
    simple_trial_specs,
    trial_specs,
    xgboost_trial_specs,
)


def test_simple_trial_menu_is_frozen_and_contains_baselines_first():
    specs = simple_trial_specs(10)
    assert [spec.model for spec in specs] == [
        "momentum", "volatility_scaled_momentum",
        "regularized_logistic", "regularized_logistic",
    ]
    assert specs[0].config["horizon_days"] == 10


def test_xgboost_is_an_opt_in_trial_without_mutating_frozen_simple_menu():
    simple_before = simple_trial_specs(10)
    assert trial_specs(10) == simple_before
    challenger = xgboost_trial_specs(10)
    combined = trial_specs(10, include_xgboost=True)
    assert combined[:len(simple_before)] == simple_before
    assert combined[len(simple_before):] == challenger
    assert challenger[0].model == "cpu_xgboost"
    assert challenger[0].config["config"]["device"] == "cpu"


def test_fixed_simple_hypotheses_are_horizon_specific_and_never_tuned():
    assert simple_hypothesis_trial_specs(10) == ()
    shock = simple_hypothesis_trial_specs(5)[0]
    residual = simple_hypothesis_trial_specs(20)[0]
    assert shock.model == residual.model == "fixed_feature_score"
    assert shock.config["shock_abs_threshold"] == 1.5
    assert residual.config["cross_sectional_percentile_lower"] == .30
    assert trial_specs(5) == simple_trial_specs(5)
    assert trial_specs(5, include_simple_hypotheses=True)[-1] == shock


def test_fixed_hypothesis_threshold_and_eligibility_are_preregistered():
    spec = simple_hypothesis_trial_specs(5)[0]
    rows = pd.DataFrame({
        "shock_reversal_eligible_5d": [True, False, True, False] * 10,
    })
    probability = np.tile([.7, .7, .3, .3], 10)
    forward = np.tile([.02, .02, -.02, -.02], 10)
    dates = pd.bdate_range("2025-01-02", periods=40)
    threshold, metrics = select_threshold_for_spec(
        spec, probability, forward, dates, rows,
        costs=UnderlyingCostModel(one_way_spread_bps=2.5, one_way_slippage_bps=2.5),
        raw_score=[2.0, 2.0, -2.0, -2.0] * 10,
    )
    assert threshold == .5
    assert metrics["threshold_policy"] == "fixed_preregistered"
    position = positions_for_spec(
        spec, probability, threshold, rows,
        raw_score=[2.0, 2.0, -2.0, -2.0] * 10,
    )
    assert position.tolist()[:4] == [1, 0, -1, 0]


def test_platt_threshold_and_calibration_are_deterministic_and_cost_aware():
    score = np.linspace(-3, 3, 120)
    label = (score + np.sin(np.arange(120)) * .2 > 0).astype(int)
    mapping = fit_platt(score, label)
    probability = mapping.apply(score)
    assert np.allclose(probability, mapping.apply(score))
    assert expected_calibration_error(probability, label) < .15
    forward = np.where(label, .02, -.02)
    dates = pd.bdate_range("2025-01-02", periods=120)
    threshold, metrics = select_threshold(
        probability, forward, dates,
        costs=UnderlyingCostModel(one_way_spread_bps=2.5,
                                  one_way_slippage_bps=2.5),
    )
    assert threshold in {.5, .55, .6, .65}
    assert metrics["training_active_dates"] >= 20
    position = positions_from_probability(probability, threshold)
    assert set(position) <= {-1, 0, 1}


def test_mutating_later_labels_cannot_change_fitted_earlier_platt_map():
    score = np.linspace(-2, 2, 100)
    label = (score > 0).astype(int)
    first = fit_platt(score[:80], label[:80])
    mutated = label.copy()
    mutated[80:] = 1 - mutated[80:]
    second = fit_platt(score[:80], mutated[:80])
    assert first == second


def test_horizon_aware_inference_and_paired_baseline_difference():
    dates = pd.bdate_range("2025-01-02", periods=80)
    index = pd.MultiIndex.from_product([dates, ["AAA", "BBB"]],
                                       names=["timestamp", "symbol"])
    net = np.tile(np.linspace(-.01, .02, 80), 2).reshape(2, 80).T.ravel()
    candidate = pd.DataFrame({
        "net_return": net,
        "position": 1,
        "probability": np.tile([.4, .6], 80),
        "direction_20d": np.tile([0, 1], 80),
    }, index=index)
    metrics = evidence_metrics(
        candidate, label_column="direction_20d",
        trial_count=4, horizon_days=20,
    )
    assert metrics["bootstrap_block_dates"] == 20
    assert metrics["sharpe_periods_per_year"] == 12
    assert "overlapping_cohort_drawdown_diagnostic" in metrics
    baseline = candidate.copy()
    baseline["net_return"] -= .001
    difference = paired_baseline_difference_metrics(
        candidate, baseline, horizon_days=20,
    )
    assert difference["net_expectancy_difference"] > 0
