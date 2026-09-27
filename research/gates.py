"""Pre-holdout development gates for frozen daily directional horizons.

The functions consume supplied development evidence only.  They have no path,
data-loader, or terminal-holdout argument, so evaluating this gate cannot open
or mutate a sealed terminal holdout.

Decision tree — ``evaluate_daily_directional_development_gate``
-----------------------------------------------------------------
    evaluate_daily_directional_development_gate(evidence_by_horizon)
    │
    ├─ protocol check: every FROZEN_HORIZONS horizon present?
    │                  no duplicates? no unsupported horizon?
    │     │
    │     └─ FAIL ──► protocol_errors non-empty
    │                 ══► HARD: overall FAIL regardless of what any
    │                     individual horizon below does — even if all three
    │                     horizons independently pass their own checks, a
    │                     protocol error still fails the whole call.
    │
    └─ for EACH horizon, evaluate_horizon_development_gate(evidence):
         │
         ├─ 1. _input_errors(evidence): finite, correctly shaped, in-range?
         │       (candidate & momentum return series, decision dates,
         │        calibrated probabilities, realized outcomes,
         │        recorded_trial_count, horizon_days ∈ FROZEN_HORIZONS)
         │     │
         │     └─ ANY fail ──► finite_complete_inputs = False
         │                     ══► HARD: this horizon is FAIL_DEVELOPMENT_ONLY
         │                         immediately. None of the 4 statistical
         │                         checks below are even computed.
         │
         └─ 2. (inputs clean) compute once, then ALL FOUR checks are HARD —
               one failing check fails the whole horizon, there is no partial
               credit:
               ┌────────────────────────────────────────┬──────────────────┐
               │ check                                    │ pass condition   │
               ├────────────────────────────────────────┼──────────────────┤
               │ candidate_minus_momentum_ci95_lower_positive │ paired bootstrap CI lower bound > 0
               │ candidate_net_expectancy_ci95_lower_positive │ candidate-alone CI lower bound > 0
               │ deflated_sharpe_lower_positive                │ Bonferroni-deflated Sharpe lower bound > 0
               │ calibration_ece_within_limit                  │ ECE ≤ MAX_EXPECTED_CALIBRATION_ERROR (0.05)
               └────────────────────────────────────────┴──────────────────┘
               A ValueError raised while computing these (e.g. too few blocks
               to bootstrap) is caught and folded back into
               finite_complete_inputs = False — the SAME hard failure as
               step 1, not a softer, separate outcome.
               │
               ├─ ALL FOUR pass ──► this horizon: PASS_DEVELOPMENT_ONLY
               └─ ANY fails      ──► this horizon: FAIL_DEVELOPMENT_ONLY

    Aggregate verdict, after every horizon has been evaluated:
         zero horizons passed            ══► HARD: overall FAIL
                                              ("no_horizons_passed")
         ≥1 horizon passed, no protocol
         errors                          ══► overall PASS, but only
                                              `passing_horizons` advance — a
                                              failed 5d horizon does not drag
                                              down an independently
                                              preregistered, passing 10d/20d
                                              horizon. `failed_horizons` is
                                              still reported, never dropped.

    What a HARD failure means, at every level above: it stops that horizon
    (or the whole call) at "development," nothing more — `passed=False`,
    status `FAIL_DEVELOPMENT_ONLY`. `terminal_holdout_accessed` is always
    `False` and stays `False` on every path through this tree, including the
    passing ones: this module has no argument through which it could open
    the sealed terminal holdout even if every check succeeded. A PASS here
    means "eligible for further shadow research," not "cleared to look at
    holdout" — only a separately preregistered, one-time holdout evaluation
    can do that (see `experiment_ledger.preregister_terminal_holdout` /
    `record_terminal_holdout_evaluation`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from .labels import FROZEN_HORIZONS
from .statistics import bonferroni_deflated_sharpe_approximation, date_block_bootstrap_ci

MAX_EXPECTED_CALIBRATION_ERROR = 0.05


@dataclass(frozen=True)
class HorizonDevelopmentEvidence:
    """Pre-holdout out-of-sample evidence for one frozen forecast horizon."""

    horizon_days: int
    candidate_net_returns: Sequence[float]
    momentum_net_returns: Sequence[float]
    decision_dates: Sequence[object]
    calibrated_probabilities: Sequence[float]
    realized_outcomes: Sequence[bool]
    recorded_trial_count: int


def _finite_vector(values: Iterable[Any], field: str) -> tuple[np.ndarray | None, str | None]:
    try:
        result = np.asarray(list(values), dtype=float)
    except (TypeError, ValueError):
        return None, f"invalid_{field}"
    if result.ndim != 1 or result.size == 0 or not np.isfinite(result).all():
        return None, f"invalid_{field}"
    return result, None


def _expected_calibration_error(probabilities: np.ndarray, outcomes: np.ndarray, bins: int = 10) -> float:
    """Fixed-bin ECE; bins and threshold are frozen for comparable development reports."""
    bucket = np.minimum((probabilities * bins).astype(int), bins - 1)
    total = float(probabilities.size)
    ece = 0.0
    for index in range(bins):
        selected = bucket == index
        if selected.any():
            ece += abs(float(probabilities[selected].mean()) - float(outcomes[selected].mean())) * float(selected.sum()) / total
    return ece


def _aggregate_returns_by_decision_date(
    candidate: np.ndarray,
    momentum: np.ndarray,
    dates: pd.DatetimeIndex,
) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Collapse correlated cross-sectional rows to one equal-weighted daily row."""
    frame = pd.DataFrame({"date": dates.normalize(), "candidate": candidate, "momentum": momentum})
    daily = frame.groupby("date", sort=True)[["candidate", "momentum"]].mean()
    return (
        daily["candidate"].to_numpy(dtype=float),
        daily["momentum"].to_numpy(dtype=float),
        pd.DatetimeIndex(daily.index),
    )


def _input_errors(evidence: HorizonDevelopmentEvidence) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    candidate, candidate_error = _finite_vector(evidence.candidate_net_returns, "candidate_net_returns")
    momentum, momentum_error = _finite_vector(evidence.momentum_net_returns, "momentum_net_returns")
    probabilities, probability_error = _finite_vector(evidence.calibrated_probabilities, "calibrated_probabilities")
    if candidate_error:
        errors.append(candidate_error)
    if momentum_error:
        errors.append(momentum_error)
    if probability_error:
        errors.append(probability_error)
    try:
        dates = pd.to_datetime(list(evidence.decision_dates), errors="coerce")
    except (TypeError, ValueError):
        dates = pd.DatetimeIndex([])
    if dates.size == 0 or pd.isna(dates).any():
        errors.append("invalid_decision_dates")
    outcomes = list(evidence.realized_outcomes)
    if not outcomes or any(not isinstance(value, (bool, np.bool_)) for value in outcomes):
        errors.append("invalid_realized_outcomes")
    elif probabilities is not None and len(outcomes) != probabilities.size:
        errors.append("calibration_length_mismatch")
    if probabilities is not None and ((probabilities < 0.0) | (probabilities > 1.0)).any():
        errors.append("invalid_calibrated_probabilities")
    if candidate is not None and momentum is not None and candidate.size != momentum.size:
        errors.append("paired_return_length_mismatch")
    if candidate is not None and dates.size != candidate.size:
        errors.append("return_date_length_mismatch")
    if not isinstance(evidence.recorded_trial_count, int) or isinstance(evidence.recorded_trial_count, bool) or evidence.recorded_trial_count < 1:
        errors.append("invalid_recorded_trial_count")
    if evidence.horizon_days not in FROZEN_HORIZONS:
        errors.append("unsupported_horizon")
    return errors, {"candidate": candidate, "momentum": momentum, "dates": dates, "probabilities": probabilities, "outcomes": outcomes}


def evaluate_horizon_development_gate(
    evidence: HorizonDevelopmentEvidence,
    *,
    bootstrap_samples: int = 2_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Evaluate the preregistered development criteria for one horizon.

    Passing is evidence for further shadow research only.  It is neither an
    option-profitability statement nor authorization to evaluate a terminal
    holdout more than its separately registered one-time evaluation.
    """
    # See "Decision tree" in the module docstring: step 1 below is the
    # finite_complete_inputs gate, step 2 is the four HARD checks that only
    # run once step 1 is clean.
    errors, data = _input_errors(evidence)
    metrics: dict[str, Any] = {
        "candidate_minus_momentum_ci95_lower": None,
        "candidate_net_expectancy_ci95_lower": None,
        "deflated_sharpe_lower": None,
        "expected_calibration_error": None,
        "effective_decision_dates": None,
        "periods_per_year": max(1, 252 // int(evidence.horizon_days)) if isinstance(evidence.horizon_days, int) and not isinstance(evidence.horizon_days, bool) and evidence.horizon_days > 0 else None,
        "bootstrap_block_size": max(5, int(evidence.horizon_days)) if isinstance(evidence.horizon_days, int) and not isinstance(evidence.horizon_days, bool) and evidence.horizon_days > 0 else None,
    }
    checks: dict[str, bool] = {"finite_complete_inputs": not errors}
    if not errors:
        candidate = data["candidate"]
        momentum = data["momentum"]
        dates = data["dates"]
        probabilities = data["probabilities"]
        outcomes = np.asarray(data["outcomes"], dtype=float)
        try:
            candidate_daily, momentum_daily, decision_dates = _aggregate_returns_by_decision_date(candidate, momentum, dates)
            # A holding horizon both reduces independent decision frequency and
            # expands the block used for serial-dependence-respecting inference.
            periods_per_year = max(1, 252 // evidence.horizon_days)
            block_size = max(5, evidence.horizon_days)
            paired_ci = date_block_bootstrap_ci(
                candidate_daily - momentum_daily, decision_dates, confidence=0.95, block_size=block_size,
                n_bootstrap=bootstrap_samples, seed=seed,
            )
            expectancy_ci = date_block_bootstrap_ci(
                candidate_daily, decision_dates, confidence=0.95, block_size=block_size,
                n_bootstrap=bootstrap_samples, seed=seed,
            )
            adjusted_sharpe = bonferroni_deflated_sharpe_approximation(
                candidate_daily, trial_count=evidence.recorded_trial_count, periods_per_year=periods_per_year,
            )
            ece = _expected_calibration_error(probabilities, outcomes)
            metrics.update({
                "candidate_minus_momentum_ci95_lower": paired_ci.lower,
                "candidate_net_expectancy_ci95_lower": expectancy_ci.lower,
                "deflated_sharpe_lower": adjusted_sharpe.lower_bound_sharpe,
                "expected_calibration_error": ece,
                "effective_decision_dates": int(candidate_daily.size),
                "periods_per_year": periods_per_year,
                "bootstrap_block_size": block_size,
            })
            checks.update({
                "candidate_minus_momentum_ci95_lower_positive": paired_ci.lower > 0.0,
                "candidate_net_expectancy_ci95_lower_positive": expectancy_ci.lower > 0.0,
                "deflated_sharpe_lower_positive": adjusted_sharpe.lower_bound_sharpe > 0.0,
                "calibration_ece_within_limit": ece <= MAX_EXPECTED_CALIBRATION_ERROR,
            })
        except ValueError as exc:
            errors.append(f"insufficient_or_invalid_evidence:{str(exc)}")
            checks["finite_complete_inputs"] = False
    failed_checks = [*errors, *(name for name, passed in checks.items() if not passed)]
    return {
        "schema_version": "daily-directional-development-gate-v1",
        "horizon_days": evidence.horizon_days,
        "status": "PASS_DEVELOPMENT_ONLY" if not failed_checks else "FAIL_DEVELOPMENT_ONLY",
        "passed": not failed_checks,
        "terminal_holdout_accessed": False,
        "checks": checks,
        "failed_checks": failed_checks,
        "metrics": metrics,
        "thresholds": {"bootstrap_confidence": 0.95, "max_expected_calibration_error": MAX_EXPECTED_CALIBRATION_ERROR},
    }


def evaluate_daily_directional_development_gate(
    evidence_by_horizon: Sequence[HorizonDevelopmentEvidence],
    **kwargs: Any,
) -> dict[str, Any]:
    """Require all three frozen daily horizons to clear before a new holdout step."""
    # Protocol check — see "Decision tree" in the module docstring: a
    # non-empty protocol_errors below is a HARD failure of the *whole* call,
    # independent of how any individual horizon scores.
    horizons = [item.horizon_days for item in evidence_by_horizon]
    invalid_set = sorted(horizon for horizon in horizons if horizon not in FROZEN_HORIZONS)
    missing = sorted(set(FROZEN_HORIZONS).difference(horizons))
    duplicates = sorted({horizon for horizon in horizons if horizons.count(horizon) > 1})
    reports = [evaluate_horizon_development_gate(item, **kwargs) for item in evidence_by_horizon]
    protocol_errors: list[str] = []
    if missing:
        protocol_errors.append(f"missing_frozen_horizons:{','.join(map(str, missing))}")
    if duplicates:
        protocol_errors.append(f"duplicate_horizons:{','.join(map(str, duplicates))}")
    if invalid_set:
        protocol_errors.append(f"unsupported_horizons:{','.join(map(str, invalid_set))}")
    passing_horizons = [report["horizon_days"] for report in reports if report["passed"]]
    failed_horizons = [report["horizon_days"] for report in reports if not report["passed"]]
    # Every frozen horizon must be evaluated, but a rejected 5d hypothesis does
    # not invalidate independently preregistered 10d/20d hypotheses.  Advance
    # only the passing horizons; a protocol error or zero passing horizons is a
    # program-level failure.
    failed_checks = list(protocol_errors)
    if not passing_horizons:
        failed_checks.append("no_horizons_passed")
    return {
        "schema_version": "daily-directional-development-gate-v1",
        "status": "PASS_DEVELOPMENT_ONLY" if not failed_checks else "FAIL_DEVELOPMENT_ONLY",
        "passed": not failed_checks,
        "terminal_holdout_accessed": False,
        "required_horizons": list(FROZEN_HORIZONS),
        "passing_horizons": passing_horizons,
        "failed_horizons": failed_horizons,
        "failed_checks": failed_checks,
        "horizons": reports,
    }
