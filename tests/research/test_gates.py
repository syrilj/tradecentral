from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.gates import (
    HorizonDevelopmentEvidence,
    evaluate_daily_directional_development_gate,
    evaluate_horizon_development_gate,
)


def _evidence(horizon: int, *, probabilities=None) -> HorizonDevelopmentEvidence:
    observations = 100
    index = np.arange(observations)
    candidate = 0.004 + 0.0002 * np.sin(index)
    momentum = 0.001 + 0.0001 * np.cos(index)
    # Exactly calibrated fixed-bin evidence: 60% observed positives at p=0.6.
    probs = np.full(observations, 0.6) if probabilities is None else probabilities
    outcomes = [index < 60 for index in range(observations)]
    return HorizonDevelopmentEvidence(
        horizon_days=horizon,
        candidate_net_returns=candidate,
        momentum_net_returns=momentum,
        decision_dates=pd.bdate_range("2020-01-02", periods=observations),
        calibrated_probabilities=probs,
        realized_outcomes=outcomes,
        recorded_trial_count=3,
    )


def test_all_frozen_horizons_pass_development_only_without_holdout_access() -> None:
    report = evaluate_daily_directional_development_gate([_evidence(5), _evidence(10), _evidence(20)], bootstrap_samples=300)
    assert report["passed"]
    assert report["status"] == "PASS_DEVELOPMENT_ONLY"
    assert not report["terminal_holdout_accessed"]
    for horizon in report["horizons"]:
        assert horizon["metrics"]["candidate_minus_momentum_ci95_lower"] > 0
        assert horizon["metrics"]["candidate_net_expectancy_ci95_lower"] > 0
        assert horizon["metrics"]["deflated_sharpe_lower"] > 0
        assert horizon["metrics"]["expected_calibration_error"] <= 0.05


def test_ece_failure_has_an_exact_structured_reason() -> None:
    report = evaluate_horizon_development_gate(_evidence(10, probabilities=np.full(100, 0.8)), bootstrap_samples=300)
    assert not report["passed"]
    assert report["status"] == "FAIL_DEVELOPMENT_ONLY"
    assert report["failed_checks"] == ["calibration_ece_within_limit"]
    assert report["metrics"]["expected_calibration_error"] == pytest.approx(0.2)


def test_nonfinite_inputs_fail_closed_and_missing_horizons_fail_protocol() -> None:
    broken = _evidence(5)
    broken = HorizonDevelopmentEvidence(**{**broken.__dict__, "candidate_net_returns": [0.01, float("nan")]})
    horizon = evaluate_horizon_development_gate(broken, bootstrap_samples=20)
    assert not horizon["passed"]
    assert "invalid_candidate_net_returns" in horizon["failed_checks"]
    overall = evaluate_daily_directional_development_gate([_evidence(5), _evidence(10)], bootstrap_samples=20)
    assert not overall["passed"]
    assert overall["failed_checks"] == ["missing_frozen_horizons:20"]


def test_sharpe_and_bootstrap_use_date_aggregates_and_horizon_scaled_settings() -> None:
    unique_dates = pd.bdate_range("2024-01-02", periods=20)
    index = np.arange(20)
    candidate_by_date = 0.004 + 0.0002 * np.sin(index)
    momentum_by_date = 0.001 + 0.0001 * np.cos(index)
    # Two symbol rows per decision date must not double the Sharpe sample size.
    evidence = HorizonDevelopmentEvidence(
        horizon_days=20,
        candidate_net_returns=np.repeat(candidate_by_date, 2),
        momentum_net_returns=np.repeat(momentum_by_date, 2),
        decision_dates=np.repeat(unique_dates, 2),
        calibrated_probabilities=np.full(40, 0.5),
        realized_outcomes=[True, False] * 20,
        recorded_trial_count=2,
    )
    report = evaluate_horizon_development_gate(evidence, bootstrap_samples=300)
    metrics = report["metrics"]
    assert report["passed"]
    assert metrics["effective_decision_dates"] == 20
    assert metrics["periods_per_year"] == 12  # floor(252 / 20)
    assert metrics["bootstrap_block_size"] == 20  # max(5, horizon_days)


def test_program_advances_passing_horizon_when_other_frozen_horizons_fail() -> None:
    report = evaluate_daily_directional_development_gate([
        _evidence(5),
        _evidence(10, probabilities=np.full(100, 0.8)),
        _evidence(20, probabilities=np.full(100, 0.8)),
    ], bootstrap_samples=300)
    assert report["passed"]
    assert report["status"] == "PASS_DEVELOPMENT_ONLY"
    assert report["passing_horizons"] == [5]
    assert report["failed_horizons"] == [10, 20]
    assert report["failed_checks"] == []


def test_program_fails_when_no_frozen_horizon_passes() -> None:
    report = evaluate_daily_directional_development_gate([
        _evidence(5, probabilities=np.full(100, 0.8)),
        _evidence(10, probabilities=np.full(100, 0.8)),
        _evidence(20, probabilities=np.full(100, 0.8)),
    ], bootstrap_samples=300)
    assert not report["passed"]
    assert report["status"] == "FAIL_DEVELOPMENT_ONLY"
    assert report["passing_horizons"] == []
    assert report["failed_horizons"] == [5, 10, 20]
    assert report["failed_checks"] == ["no_horizons_passed"]
