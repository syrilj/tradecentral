"""Behavioural tests for edge.research.bocpd (Adams & MacKay 2007, arXiv:0710.3742).

These check the algorithm's actual guarantees, not just that it runs: the
run-length posterior is a valid distribution, a known variance break is
detected near the true break point and nowhere else, truncation (§2.4)
doesn't corrupt run-length bookkeeping, and the recursion never looks ahead.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import stats as scipy_stats

from edge.research.bocpd import (
    BocpdResult,
    ConstantHazard,
    GaussianVarianceModel,
    StudentTModel,
    _student_t_logpdf,
    bocpd,
    changepoints_from_prices,
)


def _synthetic_variance_break(seed: int = 0, n_low: int = 200, n_high: int = 200,
                               sigma_low: float = 0.01, sigma_high: float = 0.05) -> np.ndarray:
    rng = np.random.default_rng(seed)
    low = rng.normal(0.0, sigma_low, size=n_low)
    high = rng.normal(0.0, sigma_high, size=n_high)
    return np.concatenate([low, high])


def _run(x: np.ndarray, *, lambda_gap: float = 250.0, truncation_mass: float = 1e-4) -> BocpdResult:
    model = GaussianVarianceModel(a=1.0, b=1e-4)
    hazard = ConstantHazard(lambda_gap=lambda_gap)
    return bocpd(x, model, hazard, truncation_mass=truncation_mass)


# ---------------------------------------------------------------------------
# Observation model unit checks (cross-checked against scipy independently of
# the dependency-free implementation used inside bocpd.py itself)
# ---------------------------------------------------------------------------


def test_student_t_logpdf_matches_scipy_independently() -> None:
    dof = np.array([2.0, 5.0, 30.5, 400.0])
    loc = np.array([0.0, -0.3, 1.2, 0.0])
    scale = np.array([1.0, 0.02, 5.0, 0.0031])
    ours = _student_t_logpdf(0.017, dof=dof, loc=loc, scale=scale)
    theirs = scipy_stats.t.logpdf(0.017, df=dof, loc=loc, scale=scale)
    np.testing.assert_allclose(ours, theirs, rtol=1e-10, atol=1e-12)


def test_gaussian_variance_model_predictive_matches_scipy_student_t() -> None:
    model = GaussianVarianceModel(a=1.0, b=1e-4)
    model.update(0.01)
    model.update(-0.02)
    log_pred = model.log_pred_prob(0.005)
    dof = 2.0 * model.a
    scale = np.sqrt(model.b / model.a)
    expected = scipy_stats.t.logpdf(0.005, df=dof, loc=0.0, scale=scale)
    np.testing.assert_allclose(log_pred, expected, rtol=1e-10, atol=1e-12)


def test_student_t_model_predictive_matches_scipy_student_t() -> None:
    model = StudentTModel(mu=0.0, kappa=1.0, alpha=1.0, beta=1.0)
    model.update(2.0)
    model.update(2.4)
    log_pred = model.log_pred_prob(2.1)
    dof = 2.0 * model.alpha
    scale = np.sqrt(model.beta * (model.kappa + 1.0) / (model.alpha * model.kappa))
    expected = scipy_stats.t.logpdf(2.1, df=dof, loc=model.mu, scale=scale)
    np.testing.assert_allclose(log_pred, expected, rtol=1e-10, atol=1e-12)


def test_gaussian_variance_model_rejects_bad_priors() -> None:
    with pytest.raises(ValueError):
        GaussianVarianceModel(a=0.0)
    with pytest.raises(ValueError):
        GaussianVarianceModel(b=-1.0)


def test_student_t_model_rejects_bad_priors() -> None:
    with pytest.raises(ValueError):
        StudentTModel(kappa=0.0)
    with pytest.raises(ValueError):
        StudentTModel(alpha=-1.0)
    with pytest.raises(ValueError):
        StudentTModel(beta=0.0)


# ---------------------------------------------------------------------------
# Contract behaviours
# ---------------------------------------------------------------------------


def test_run_length_posterior_sums_to_one_at_every_bar() -> None:
    x = _synthetic_variance_break(seed=1)
    result = _run(x)
    matrix = result.run_length_posterior()
    column_sums = matrix.sum(axis=0)
    np.testing.assert_allclose(column_sums, np.ones(len(x)), atol=1e-9)
    # Same invariant holds for the raw per-bar posteriors bocpd() actually
    # carries forward (before densifying into the matrix).
    for _labels, probs in result.run_length_posteriors:
        assert probs.sum() == pytest.approx(1.0, abs=1e-9)


def test_cp_prob_equals_hazard_rate_under_constant_hazard_by_construction() -> None:
    """Document (and pin down) a real, easily-missed property of BOCPD.

    Under a CONSTANT hazard H, P(r_t=0|x_1:t) is provably equal to H at
    every bar, independent of the data: the paper's eq. 3-4 reuse the same
    pi_t^(r) predictive in both the "grow" (weight 1-H) and "reset" (weight
    H) branches for a given r_{t-1}, so those weights factor out of both the
    numerator and the evidence and cancel exactly, regardless of how well
    the data fits. This was verified independently (outside this codebase)
    with a hand-rolled scipy-based recursion before relying on it here.

    This means `cp_prob_raw` alone is NOT the right signal for "did a break
    just happen" -- see `test_break_prob_spikes_at_the_true_break_and_nowhere_else`
    and `test_known_variance_break_collapses_run_length...` below for the
    fields that actually respond to the data.

    Uses truncation_mass=0 deliberately: §2.4 truncation renormalizes after
    dropping low-mass hypotheses, which perturbs every surviving probability
    (including row 0) by a factor of order `truncation_mass` -- an accepted,
    separately-tested trade-off (see the truncation-invariance test), not
    part of the identity being pinned down here.
    """
    x = _synthetic_variance_break(seed=42)
    result = _run(x, lambda_gap=250.0, truncation_mass=0.0)
    expected_h = 1.0 / 250.0
    np.testing.assert_allclose(result.cp_prob_raw, expected_h, atol=1e-9)

    # Different hazard -> different (still constant) cp_prob_raw.
    result_fast = _run(x, lambda_gap=50.0, truncation_mass=0.0)
    np.testing.assert_allclose(result_fast.cp_prob_raw, 1.0 / 50.0, atol=1e-9)


def test_cp_prob_raw_equals_hazard_with_default_truncation_too() -> None:
    """Same identity as above, but with the default truncation_mass=1e-4 --
    documents that it still holds to within the truncation-induced
    renormalization noise (see the truncation-invariance test for that
    trade-off's magnitude), so nobody "fixes" cp_prob_raw back into a signal
    after looking at a truncated run and seeing it isn't bit-exact.
    """
    x = _synthetic_variance_break(seed=7)
    result = _run(x, lambda_gap=250.0)
    assert np.max(np.abs(result.cp_prob_raw - 1.0 / 250.0)) < 1e-6


def test_known_variance_break_collapses_run_length_and_nowhere_else() -> None:
    n_low, n_high = 200, 200
    x = _synthetic_variance_break(seed=42, n_low=n_low, n_high=n_high, sigma_low=0.01, sigma_high=0.05)
    result = _run(x, lambda_gap=250.0)

    break_idx = n_low  # 0-indexed bar where the high-variance regime starts
    just_before = result.expected_run_length[break_idx - 1]
    shortly_after = result.expected_run_length[break_idx:break_idx + 8].min()
    assert shortly_after < just_before * 0.5, (
        "expected run length should drop sharply within a few bars of the true break"
    )
    assert result.map_run_length[break_idx:break_idx + 8].min() <= 5, (
        "MAP run length should collapse toward 0 shortly after the break"
    )

    # Mid-segment quiet zones: well away from both the break and the boundary
    # effects at t=0, run length should keep growing, not randomly collapse.
    quiet_low_start, quiet_low_end = 40, n_low - 40
    quiet_high_start, quiet_high_end = n_low + 40, n_low + n_high - 20
    assert result.map_run_length[quiet_low_end] > result.map_run_length[quiet_low_start]
    assert result.map_run_length[quiet_high_end] > result.map_run_length[quiet_high_start]


def test_break_prob_spikes_at_the_true_break_and_nowhere_else() -> None:
    """The actual data-responsive detection statistic (unlike cp_prob_raw).

    break_prob = P(r_t <= 5 | x_1:t) should shoot toward 1 within a few bars
    of a real break and stay low through both stationary segments.
    """
    n_low, n_high = 200, 200
    x = _synthetic_variance_break(seed=42, n_low=n_low, n_high=n_high, sigma_low=0.01, sigma_high=0.05)
    result = _run(x, lambda_gap=250.0)

    break_idx = n_low
    assert result.break_prob[break_idx:break_idx + 3].max() > 0.5, (
        "break_prob should exceed 0.5 within 3 bars of the true break"
    )
    assert result.break_prob_20[break_idx:break_idx + 3].max() > 0.5

    # "Stays low" is a distributional claim on stochastic data, not a
    # per-bar guarantee -- a single 3-4 sigma draw in 400 iid samples can
    # legitimately nudge break_prob up for a bar or two without meaning
    # anything. Use robust (median/quantile) statistics rather than a brittle
    # max, so the test isn't flaky on an occasional true outlier.
    quiet_low = slice(40, n_low - 40)
    quiet_high = slice(n_low + 40, n_low + n_high - 20)
    assert np.median(result.break_prob[quiet_low]) < 0.05
    assert np.quantile(result.break_prob[quiet_low], 0.95) < 0.3
    assert np.median(result.break_prob[quiet_high]) < 0.05
    assert np.quantile(result.break_prob[quiet_high], 0.95) < 0.3


def test_stationary_series_has_growing_run_length_and_low_break_prob() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(0.0, 0.015, size=300)
    result = _run(x, lambda_gap=250.0)

    # "Roughly monotonic": look at a coarse trailing window average late in
    # the series versus early -- growth should dominate resets on a truly
    # stationary series, even though any individual bar can dip.
    early = result.map_run_length[20:60].mean()
    late = result.map_run_length[240:280].mean()
    assert late > early

    # cp_prob_raw is pinned at the hazard rate by construction (see the
    # dedicated identity test); break_prob is the field that should actually
    # stay low on a series with no real break.
    assert result.break_prob.mean() < 0.15
    assert np.median(result.break_prob) < 0.05


def test_pred_std_recovers_the_true_sigma_on_stationary_series() -> None:
    """This is the test that would have caught the pred_var floor bug: a
    naive implementation that floors the undefined-variance r=0 row into a
    finite constant produces the SAME pred_std regardless of the data's
    actual scale, which passes any "is it finite" check but is meaningless.
    """
    rng = np.random.default_rng(21)
    for true_sigma in (0.005, 0.05):
        x = rng.normal(0.0, true_sigma, size=400)
        result = _run(x, lambda_gap=250.0)
        # Settle past the initial transient so early-run uncertainty doesn't
        # dominate the comparison.
        settled = result.pred_std[100:]
        assert np.isfinite(settled).all()
        recovered = float(np.median(settled))
        assert recovered == pytest.approx(true_sigma, rel=0.2), (
            f"pred_std should track true sigma={true_sigma}, got median={recovered}"
        )


def test_truncation_matches_no_truncation_closely_on_a_short_series() -> None:
    x = _synthetic_variance_break(seed=3, n_low=60, n_high=60)
    truncated = _run(x, truncation_mass=1e-4)
    untruncated = _run(x, truncation_mass=0.0)
    diff = np.abs(truncated.cp_prob_raw - untruncated.cp_prob_raw)
    assert diff.max() < 1e-3
    diff_break = np.abs(truncated.break_prob - untruncated.break_prob)
    assert diff_break.max() < 1e-3


def test_truncation_preserves_run_length_identity() -> None:
    # A long-enough stationary run so pruning actually fires (otherwise this
    # test would pass vacuously without ever exercising _truncation_mask).
    rng = np.random.default_rng(11)
    x = rng.normal(0.0, 0.01, size=400)
    result = _run(x, truncation_mass=1e-3)
    pruned_at_some_bar = any(len(labels) < t + 1 for t, (labels, _p) in enumerate(result.run_length_posteriors))
    assert pruned_at_some_bar, "test is only meaningful if truncation actually drops hypotheses"

    # label 0 (a possible fresh break) is always protected, so it survives
    # every bar -- but pruning should still be creating genuine *gaps* in the
    # middle of the surviving label set (not just trimming one end), which is
    # exactly why bocpd() cannot assume array position == run length.
    late_labels, _late_probs = result.run_length_posteriors[-1]
    assert late_labels.min() == 0
    contiguous_span = late_labels.max() - late_labels.min() + 1
    assert late_labels.size < contiguous_span, "pruning should have left holes, not just trimmed one end"

    # map_run_length must always be a valid, causally-bounded true run
    # length: never negative, never exceeding bars elapsed -- this is only
    # possible if pruning correctly preserved run-length identity instead of
    # reporting a pruned-array index. At 0-indexed bar t, the maximum
    # possible true run length is t+1 (r_0=0 before any data, so after the
    # first observation r_1 can reach 1).
    assert (result.map_run_length >= 0).all()
    assert (result.map_run_length <= np.arange(1, len(x) + 1)).all()
    # And it should track the untruncated run's belief reasonably closely --
    # this truncation_mass (1e-3, chosen aggressively so pruning reliably
    # fires within 400 bars) is 10x the paper's own default, so some drift
    # from the untruncated run is expected; the tight bound on the default
    # 1e-4 setting is covered separately by the truncation-invariance test.
    # What matters here is that it stays in the right ballpark, confirming
    # pruning didn't corrupt the run-length bookkeeping into nonsense.
    untruncated = _run(x, truncation_mass=0.0)
    relative_drift = np.abs(result.expected_run_length - untruncated.expected_run_length) / np.maximum(
        untruncated.expected_run_length, 1.0
    )
    assert relative_drift.max() < 0.1


def test_no_lookahead_prefix_run_is_byte_identical() -> None:
    x = _synthetic_variance_break(seed=5, n_low=120, n_high=120)
    k = 150
    full = _run(x)
    prefix = _run(x[:k])
    np.testing.assert_array_equal(full.cp_prob_raw[:k], prefix.cp_prob_raw[:k])
    np.testing.assert_array_equal(full.break_prob[:k], prefix.break_prob[:k])
    np.testing.assert_array_equal(full.break_prob_20[:k], prefix.break_prob_20[:k])
    np.testing.assert_array_equal(full.map_run_length[:k], prefix.map_run_length[:k])
    np.testing.assert_array_equal(full.expected_run_length[:k], prefix.expected_run_length[:k])
    np.testing.assert_array_equal(full.pred_mean[:k], prefix.pred_mean[:k])
    np.testing.assert_array_equal(full.pred_std[:k], prefix.pred_std[:k])


def test_numerical_stability_over_a_long_series() -> None:
    rng = np.random.default_rng(99)
    # Mix in a couple of regime changes so the run-length distribution isn't
    # trivially collapsed the whole way through.
    x = np.concatenate([
        rng.normal(0.0, 0.01, size=700),
        rng.normal(0.0, 0.06, size=600),
        rng.normal(0.0, 0.02, size=700),
    ])
    result = _run(x)
    for arr in (result.cp_prob_raw, result.break_prob, result.break_prob_20,
                result.expected_run_length, result.pred_mean, result.pred_std,
                result.pred_var_defined_mass):
        assert np.isfinite(arr).all()
    assert np.isfinite(result.run_length_posterior()).all()
    # Allow a hair of float64 slack: summing a probability subset can
    # overshoot 1.0 by a couple of ULPs, which is not the underflow/NaN this
    # test is actually checking for.
    tol = 1e-9
    assert (result.cp_prob_raw >= -tol).all() and (result.cp_prob_raw <= 1.0 + tol).all()
    assert (result.break_prob >= -tol).all() and (result.break_prob <= 1.0 + tol).all()


def test_input_validation_raises_value_error() -> None:
    model = GaussianVarianceModel()
    hazard = ConstantHazard(lambda_gap=250.0)
    with pytest.raises(ValueError):
        bocpd(np.array([]), model, hazard)
    with pytest.raises(ValueError):
        bocpd(np.array([0.01, np.nan, 0.02]), GaussianVarianceModel(), hazard)
    with pytest.raises(ValueError):
        bocpd(np.array([0.01, np.inf]), GaussianVarianceModel(), hazard)
    with pytest.raises(ValueError):
        ConstantHazard(lambda_gap=1.0)
    with pytest.raises(ValueError):
        ConstantHazard(lambda_gap=0.5)


def test_bocpd_rejects_a_reused_model() -> None:
    model = GaussianVarianceModel()
    hazard = ConstantHazard(lambda_gap=250.0)
    bocpd(np.array([0.01, -0.02, 0.015]), model, hazard)
    with pytest.raises(ValueError):
        bocpd(np.array([0.01, -0.02]), model, hazard)


# ---------------------------------------------------------------------------
# changepoints_from_prices convenience wrapper
# ---------------------------------------------------------------------------


def test_changepoints_from_prices_forms_simple_returns_and_drops_first_nan() -> None:
    import pandas as pd

    dates = pd.bdate_range("2026-01-02", periods=50)
    rng = np.random.default_rng(13)
    log_steps = rng.normal(0.0, 0.01, size=len(dates))
    close = pd.Series(100.0 * np.exp(np.cumsum(log_steps)), index=dates)

    result = changepoints_from_prices(close, lambda_gap=250.0, a=1.0, b=1e-4)
    assert result.n_bars == len(dates) - 1

    expected_returns = close.pct_change(fill_method=None).dropna().to_numpy()
    manual = _run(expected_returns, lambda_gap=250.0)
    np.testing.assert_array_equal(result.cp_prob_raw, manual.cp_prob_raw)
    np.testing.assert_array_equal(result.break_prob, manual.break_prob)


def test_changepoints_from_prices_rejects_bad_input() -> None:
    import pandas as pd

    with pytest.raises(ValueError):
        changepoints_from_prices([1.0, 2.0, 3.0])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        changepoints_from_prices(pd.Series([100.0], index=pd.bdate_range("2026-01-02", periods=1)))
