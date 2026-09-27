from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import math
from edge.research.kalman_trend import kalman_trend
from edge.research.regimes import (
    classify_regimes,
    compute_cusum_transition_risk,
    compute_market_structure,
    compute_ou_half_life,
    compute_rolling_volatility_regime,
    compute_variance_ratio,
    performance_by_regime,
    slice_by_regime,
)
from edge.research.statistics import (
    bonferroni_deflated_sharpe_approximation,
    date_block_bootstrap_ci,
    effective_trial_count_from_correlation,
    effective_trial_count_from_returns,
    trial_return_correlation_matrix,
)


def test_date_block_bootstrap_is_reproducible_and_date_aware() -> None:
    dates = pd.bdate_range("2024-01-01", periods=30)
    # Two positions per date: the CI treats a date as one resampling unit.
    returns = np.repeat(np.linspace(-0.002, 0.004, len(dates)), 2)
    repeated_dates = np.repeat(dates, 2)
    first = date_block_bootstrap_ci(returns, repeated_dates, block_size=4, n_bootstrap=300, seed=7)
    second = date_block_bootstrap_ci(returns, repeated_dates, block_size=4, n_bootstrap=300, seed=7)
    assert first == second
    assert first.n_dates == 30
    assert first.lower <= first.estimate <= first.upper


def test_search_adjustment_is_more_conservative_with_more_trials() -> None:
    returns = np.array([0.002, -0.001, 0.003, 0.001, -0.0005] * 20)
    one = bonferroni_deflated_sharpe_approximation(returns, trial_count=1)
    many = bonferroni_deflated_sharpe_approximation(returns, trial_count=100)
    assert many.lower_bound_sharpe < one.lower_bound_sharpe < one.observed_sharpe
    with pytest.raises(ValueError, match="non-zero"):
        bonferroni_deflated_sharpe_approximation([0.01, 0.01], trial_count=1)


def test_regime_classification_is_causal_under_future_mutation_and_slices_results() -> None:
    index = pd.bdate_range("2023-01-02", periods=150)
    prices = pd.Series(100 * np.exp(np.linspace(0, 0.25, len(index))), index=index, name="close")
    baseline = classify_regimes(prices, volatility_window=10, trend_window=20)
    changed = prices.copy()
    changed.iloc[120:] *= 0.2
    mutated = classify_regimes(changed, volatility_window=10, trend_window=20)
    pd.testing.assert_frame_equal(baseline.iloc[:120], mutated.iloc[:120])
    records = baseline.iloc[80:].copy()
    records["net_return"] = np.linspace(-0.01, 0.02, len(records))
    slices = slice_by_regime(records)
    summary = performance_by_regime(records)
    assert slices
    assert int(summary["n"].sum()) == len(records)
    assert {"mean_return", "median_return", "win_rate"}.issubset(summary.columns)


def test_rolling_volatility_percentile_eliminates_expanding_drift() -> None:
    """Trailing 252d percentile recovers low-vol baseline after historical shock clears."""
    rng = np.random.default_rng(123)
    n = 600
    idx = pd.bdate_range("2022-01-03", periods=n)
    # Bars 0..200: Low vol (sigma=0.008)
    # Bars 200..300: High vol shock (sigma=0.04)
    # Bars 300..600: Low vol (sigma=0.008)
    shocks = np.concatenate([
        rng.normal(0.0, 0.008, 200),
        rng.normal(0.0, 0.04, 100),
        rng.normal(0.0, 0.008, 300),
    ])
    prices = pd.Series(100.0 * np.exp(np.cumsum(shocks)), index=idx, name="close")

    result = compute_rolling_volatility_regime(prices, vol_window=20, percentile_window=252)

    # During the shock (bar 250), percentile ranking vs prior 200 low-vol bars is high
    assert result.volatility_percentile.iloc[250] > 0.85

    # 252 bars after the shock ended (bar 570), the trailing 252d window contains only
    # low-vol bars, so the percentile ranking recalibrates back to the middle (~0.50).
    calibrated_pct = result.volatility_percentile.iloc[560:590].mean()
    assert 0.30 <= calibrated_pct <= 0.70


def test_variance_ratio_synthetic_regimes() -> None:
    """Lo-MacKinlay VR(5) distinguishes random walk, momentum, and mean reversion."""
    rng = np.random.default_rng(42)
    n = 1000

    # 1. Random walk: VR ~ 1.0
    rw_ret = rng.normal(0.0, 0.01, n)
    rw_log_p = np.cumsum(rw_ret)
    vr_rw = compute_variance_ratio(rw_log_p, q=5)
    assert 0.85 <= vr_rw <= 1.15

    # 2. Autoregressive momentum: r_t = 0.5 * r_{t-1} + e_t -> VR > 1.2
    mom_ret = np.zeros(n)
    for t in range(1, n):
        mom_ret[t] = 0.5 * mom_ret[t - 1] + rng.normal(0.0, 0.01)
    mom_log_p = np.cumsum(mom_ret)
    vr_mom = compute_variance_ratio(mom_log_p, q=5)
    assert vr_mom > 1.20

    # 3. Mean-reverting series: x_t = -0.5 * x_{t-1} + e_t -> VR < 0.85
    mr_ret = np.zeros(n)
    for t in range(1, n):
        mr_ret[t] = -0.4 * mr_ret[t - 1] + rng.normal(0.0, 0.01)
    mr_log_p = np.cumsum(mr_ret)
    vr_mr = compute_variance_ratio(mr_log_p, q=5)
    assert vr_mr < 0.85


def test_ou_half_life_recovery() -> None:
    """Estimate OU half-life matches theoretical target."""
    rng = np.random.default_rng(99)
    n = 500
    # Known half-life t_half = 10.0 -> theta = ln(2)/10 -> beta = exp(-theta) = 2^(-0.1) ~ 0.933
    target_half_life = 10.0
    theta = math.log(2.0) / target_half_life
    beta = math.exp(-theta)

    x = np.zeros(n)
    for t in range(1, n):
        x[t] = beta * x[t - 1] + rng.normal(0.0, 1.0)
    prices = 100.0 + x

    est_half_life = compute_ou_half_life(prices, window=500)
    assert est_half_life == pytest.approx(target_half_life, abs=2.0)


def test_kalman_velocity_zscore_scale_free() -> None:
    """Kalman velocity z-score is scale-free across small-cap vs mega-cap price scales."""
    rng = np.random.default_rng(77)
    n = 200
    idx = pd.bdate_range("2024-01-02", periods=n)
    ret = 0.002 + rng.normal(0.0, 0.01, n)
    p_small = pd.Series(5.0 * np.exp(np.cumsum(ret)), index=idx)
    p_large = pd.Series(5000.0 * np.exp(np.cumsum(ret)), index=idx)

    res_small = kalman_trend(p_small, q=1e-6, noise_days=20)
    res_large = kalman_trend(p_large, q=1e-6, noise_days=20)

    # Score (velocity z-score) must be identical
    np.testing.assert_allclose(res_small.score, res_large.score, atol=1e-9)
    assert (res_small.trend_state == res_large.trend_state).all()


def test_transition_risk_spikes_on_volatility_break() -> None:
    """CUSUM and composite transition hazard spike on sudden volatility breaks."""
    rng = np.random.default_rng(55)
    n = 300
    # 200 quiet bars followed by sudden 5-sigma shock
    quiet = rng.normal(0.0, 0.005, 200)
    shock = rng.normal(-0.04, 0.03, 100)
    returns = pd.Series(np.concatenate([quiet, shock]))

    res = compute_cusum_transition_risk(returns, vol_window=20, k=0.5, h=4.0)

    # Quiet period transition risk is low/moderate
    assert res.transition_risk.iloc[50:180].mean() < 0.35
    # Transition risk spikes during the shock
    assert res.transition_risk.iloc[201:220].max() > 0.75


def test_zero_variance_and_warmup_hygiene() -> None:
    """Constant price input produces clean bounded values without division errors."""
    n = 100
    idx = pd.bdate_range("2024-01-02", periods=n)
    flat = pd.Series(np.full(n, 50.0), index=idx, name="close")

    vol_res = compute_rolling_volatility_regime(flat, vol_window=20, percentile_window=60)
    assert (vol_res.realized_volatility.dropna() == 0.0).all()
    assert vol_res.volatility_shock.sum() == 0

    struct_res = compute_market_structure(flat, vr_window=40, ou_window=30)
    assert (struct_res.variance_ratio_5.dropna() == 1.0).all()
    assert (struct_res.market_structure == "RANGE_BOUND").all()


# ---------------------------------------------------------------------------
# Effective trial count (K_eff, architecture spec S11.4) -- P1-7 validation.
#
# These tests exist to make an implementation bug in K_eff visible, not to
# rubber-stamp whatever the code currently returns.  Golden vectors are
# checked against analytically-known answers derived independently of the
# implementation, not against the implementation's own output.
# ---------------------------------------------------------------------------


def _orthogonal_returns(n_obs: int, k: int, seed: int) -> np.ndarray:
    """K return columns that are exactly demeaned and mutually orthogonal.

    QR of a *demeaned* random matrix yields orthonormal columns that are
    still demeaned (any linear combination of demeaned columns is demeaned),
    so the resulting sample correlation matrix is the identity up to
    floating-point roundoff -- an exact, non-random-across-runs way to
    manufacture a genuinely uncorrelated trial panel.
    """
    rng = np.random.default_rng(seed)
    raw = rng.normal(size=(n_obs, k))
    raw -= raw.mean(axis=0, keepdims=True)
    q, _ = np.linalg.qr(raw)
    return q[:, :k]


def _block_factor_returns(n_obs: int, block_sizes: tuple[int, ...], seed: int) -> np.ndarray:
    """Trials formed from ``len(block_sizes)`` mutually orthogonal factors.

    Each factor is replicated to fill one block, so trials sharing a factor
    are *identical* (correlation 1) and trials in different blocks are
    exactly uncorrelated (correlation 0) -- a block-diagonal correlation
    matrix by construction, not by fitting.
    """
    factors = _orthogonal_returns(n_obs, len(block_sizes), seed)
    columns = [factors[:, i] for i, size in enumerate(block_sizes) for _ in range(size)]
    return np.column_stack(columns)


def _equicorrelation(k: int, rho: float) -> np.ndarray:
    matrix = np.full((k, k), rho)
    np.fill_diagonal(matrix, 1.0)
    return matrix


def test_effective_trial_count_orthogonal_trials_equal_raw_count() -> None:
    """Golden vector: uncorrelated trials are fully independent -> K_eff == K."""
    for k in (1, 2, 5, 10):
        result = effective_trial_count_from_correlation(np.eye(k))
        assert result.raw_trial_count == k
        assert result.effective_trial_count == pytest.approx(float(k), abs=1e-6)
        assert result.diagnostic_only is True
    for n_obs, k in ((40, 3), (80, 6), (200, 8)):
        returns = _orthogonal_returns(n_obs, k, seed=11)
        result = effective_trial_count_from_returns(returns)
        assert result.effective_trial_count == pytest.approx(float(k), abs=1e-6)
        assert result.n_observations == n_obs


def test_effective_trial_count_identical_trials_equal_one() -> None:
    """Golden vector: perfectly redundant trials carry one bit of search -> K_eff == 1."""
    for k in (2, 5, 9):
        result = effective_trial_count_from_correlation(np.ones((k, k)))
        assert result.effective_trial_count == pytest.approx(1.0, abs=1e-6)
    rng = np.random.default_rng(3)
    base = rng.normal(size=120)
    for k in (2, 5, 9):
        returns = np.column_stack([base] * k)
        result = effective_trial_count_from_returns(returns)
        assert result.effective_trial_count == pytest.approx(1.0, abs=1e-6)


def test_effective_trial_count_equal_blocks_equal_number_of_blocks() -> None:
    """Golden vector, derived by hand: M equal-sized fully-correlated blocks -> K_eff == M.

    A block of b identical trials has correlation submatrix ``ones((b, b))``,
    which is rank 1 (spanned by the all-ones vector) with eigenvalues
    ``{b, 0, 0, ..., 0}`` (b-1 zeros).  Stacking M such blocks block-diagonally
    (trials in different blocks exactly uncorrelated) gives M nonzero
    eigenvalues, one per block, each equal to that block's size.  When every
    block has the same size b = K / M, each nonzero eigenvalue equals b, so
    p_m = b / (M * b) = 1 / M for m = 1..M: a uniform distribution over M
    outcomes.  Shannon entropy of that distribution is ln(M), so
    K_eff = exp(ln M) = M exactly.
    """
    for block_sizes in ((3, 3), (2, 2, 2), (4, 4, 4, 4), (5, 5)):
        total = sum(block_sizes)
        correlation = np.zeros((total, total))
        offset = 0
        for size in block_sizes:
            correlation[offset:offset + size, offset:offset + size] = 1.0
            offset += size
        result = effective_trial_count_from_correlation(correlation)
        assert result.effective_trial_count == pytest.approx(float(len(block_sizes)), abs=1e-6)
    for block_sizes, n_obs in (((3, 3), 60), ((2, 2, 2), 90), ((4, 4, 4, 4), 200), ((5, 5), 40)):
        returns = _block_factor_returns(n_obs, block_sizes, seed=5)
        result = effective_trial_count_from_returns(returns)
        assert result.effective_trial_count == pytest.approx(float(len(block_sizes)), abs=1e-6)


def test_effective_trial_count_never_loosens_the_deflated_sharpe_gate() -> None:
    """Regression guard for the CRITICAL CONSTRAINT: K_eff must not gate.

    Build a panel with a large raw trial count but a small effective count
    (many near-duplicate trials), then confirm that substituting K_eff for
    trial_count -- which nothing in this codebase should ever do -- would
    make the gate strictly *easier* to pass than gating on the raw count.
    That would be exactly backwards for a project whose retracted GO calls
    were both false positives from under-corrected search, which is why
    ``bonferroni_deflated_sharpe_approximation`` must keep taking the raw,
    pre-registered trial count and nothing derived from the trial returns.
    """
    block_sizes = (12, 4, 4)  # raw K = 20, but only 3 independent factors
    n_obs = 300
    returns = _block_factor_returns(n_obs, block_sizes, seed=9)
    raw_k = sum(block_sizes)
    k_eff = effective_trial_count_from_returns(returns).effective_trial_count
    assert k_eff < raw_k  # the whole premise of the hazard being guarded against

    rng = np.random.default_rng(9)
    candidate_returns = 0.0004 + rng.normal(scale=0.01, size=400)
    correct = bonferroni_deflated_sharpe_approximation(candidate_returns, trial_count=raw_k)
    if_misused = bonferroni_deflated_sharpe_approximation(
        candidate_returns, trial_count=max(1, round(k_eff))
    )
    assert if_misused.critical_z < correct.critical_z
    assert if_misused.lower_bound_sharpe > correct.lower_bound_sharpe


def test_effective_trial_count_synthetic_null_recovers_known_structure() -> None:
    """Synthetic null: sample K_eff should concentrate near the population K_eff.

    Draws many independent samples from a *known* equicorrelated population
    and checks the distribution of the sample estimate, not one lucky draw:
    the mean should track the analytically-known population K_eff, the
    spread should shrink as the sample size grows, and every draw must stay
    inside the mathematically-required [1, K] bound.
    """
    scenarios = [
        {"k": 10, "rho": 0.3, "n_obs": 500},
        {"k": 10, "rho": 0.3, "n_obs": 60},
        {"k": 8, "rho": 0.8, "n_obs": 250},
        {"k": 6, "rho": 0.0, "n_obs": 300},
    ]
    n_seeds = 250
    distributions: dict[tuple[int, float, int], np.ndarray] = {}
    for scenario in scenarios:
        k, rho, n_obs = scenario["k"], scenario["rho"], scenario["n_obs"]
        population = _equicorrelation(k, rho)
        expected = effective_trial_count_from_correlation(population).effective_trial_count
        samples = np.empty(n_seeds, dtype=float)
        for seed in range(n_seeds):
            rng = np.random.default_rng(seed)
            draws = rng.multivariate_normal(mean=np.zeros(k), cov=population, size=n_obs)
            samples[seed] = effective_trial_count_from_returns(draws).effective_trial_count
        distributions[(k, rho, n_obs)] = samples
        assert np.isfinite(samples).all()
        assert (samples >= 1.0 - 1e-9).all() and (samples <= k + 1e-9).all()
        tolerance = 0.35 if n_obs >= 200 else 0.75
        assert samples.mean() == pytest.approx(expected, abs=tolerance), (
            f"k={k} rho={rho} n_obs={n_obs}: mean(K_eff)={samples.mean():.4f} vs "
            f"population K_eff={expected:.4f} over {n_seeds} seeds "
            f"(std={samples.std():.4f}, min={samples.min():.4f}, max={samples.max():.4f})"
        )
    # More observations should concentrate the estimator more tightly around
    # the same population target (k=10, rho=0.3 run at two sample sizes).
    tight = distributions[(10, 0.3, 500)]
    loose = distributions[(10, 0.3, 60)]
    assert tight.std() < loose.std()


def test_effective_trial_count_numerical_hygiene() -> None:
    """No golden-vector or synthetic-null input may produce NaN or leave [1, K]."""
    # A single trial: no correlation to estimate, K_eff is trivially 1.
    single = effective_trial_count_from_correlation(np.array([[1.0]]))
    assert single.effective_trial_count == 1.0
    single_from_returns = effective_trial_count_from_returns(np.array([[0.01], [0.02], [-0.03]]))
    assert single_from_returns.effective_trial_count == 1.0
    single_one_obs = effective_trial_count_from_returns(np.array([[0.01]]))
    assert single_one_obs.effective_trial_count == 1.0

    # Near-singular: two trials correlated at 1 - 1e-10, not exactly 1.
    near_singular = effective_trial_count_from_correlation(
        np.array([[1.0, 1.0 - 1e-10], [1.0 - 1e-10, 1.0]])
    )
    assert np.isfinite(near_singular.effective_trial_count)
    assert 1.0 <= near_singular.effective_trial_count <= 2.0

    # Tiny negative eigenvalues from floating-point noise (this exact block
    # matrix produces eigenvalues on the order of -1e-16 from eigvalsh):
    # must clip to zero, not propagate as NaN.
    block = np.zeros((6, 6))
    block[0:3, 0:3] = 1.0
    block[3:6, 3:6] = 1.0
    noisy = effective_trial_count_from_correlation(block)
    assert np.isfinite(noisy.effective_trial_count)
    assert all(v >= 0.0 for v in noisy.eigenvalues)
    assert 1.0 <= noisy.effective_trial_count <= 6.0

    # Constant (zero-variance) trial series mixed with real ones.
    rng = np.random.default_rng(21)
    normal_col = rng.normal(size=60)
    mixed = np.column_stack([
        normal_col,
        np.full(60, 3.14159),
        normal_col * 2.0 + rng.normal(scale=0.01, size=60),
    ])
    mixed_result = effective_trial_count_from_returns(mixed)
    assert np.isfinite(mixed_result.effective_trial_count)
    assert 1.0 <= mixed_result.effective_trial_count <= 3.0 + 1e-9

    # All trials constant/zero-variance: each is uncorrelated with the
    # others (covariance with anything is exactly zero for a constant
    # series), so this must not raise or produce NaN.
    all_constant = np.column_stack([np.full(15, 1.0), np.full(15, -2.0), np.full(15, 0.0)])
    all_constant_result = effective_trial_count_from_returns(all_constant)
    assert np.isfinite(all_constant_result.effective_trial_count)
    assert 1.0 <= all_constant_result.effective_trial_count <= 3.0 + 1e-9

    # More trials than observations: correlation matrix is guaranteed
    # rank-deficient (several exactly/near-zero eigenvalues).
    rng = np.random.default_rng(22)
    fat = rng.normal(size=(5, 25))
    fat_result = effective_trial_count_from_returns(fat)
    assert np.isfinite(fat_result.effective_trial_count)
    assert 1.0 <= fat_result.effective_trial_count <= 25.0 + 1e-9

    # Broad randomized sweep: many random (and possibly rank-deficient)
    # correlation matrices must never produce NaN or leave [1, K].
    rng = np.random.default_rng(23)
    for _ in range(200):
        k = int(rng.integers(1, 12))
        n_obs = int(rng.integers(1, 40))
        returns = rng.normal(size=(n_obs, k))
        if n_obs >= 2 and k >= 2 and rng.random() < 0.3:
            zeroed = rng.choice(k, size=rng.integers(1, k + 1), replace=False)
            returns[:, zeroed] = rng.normal()
        try:
            result = effective_trial_count_from_returns(returns)
        except ValueError:
            # Only the documented "need >= 2 observations for K > 1 trials"
            # guard may reject an input here.
            assert not (n_obs >= 2 or k == 1)
            continue
        assert np.isfinite(result.effective_trial_count)
        assert 1.0 - 1e-9 <= result.effective_trial_count <= k + 1e-9


def test_effective_trial_count_rejects_materially_non_psd_correlation() -> None:
    """A materially negative eigenvalue means an invalid correlation matrix; must raise, not clip."""
    broken = np.array([[1.0, 0.0], [0.0, -0.5]])  # eigenvalues 1.0, -0.5
    with pytest.raises(ValueError, match="not positive semi-definite"):
        effective_trial_count_from_correlation(broken)


def test_effective_trial_count_rejects_materially_asymmetric_correlation() -> None:
    """A materially asymmetric input must raise, not silently read one triangle.

    ``np.linalg.eigvalsh`` reads only one triangle of its input by design,
    so without this explicit check a corruption confined to the other
    triangle would silently vanish (see
    ``test_independent_implementation_reads_both_triangles`` in
    test_effective_trial_count_cross_check.py for a direct demonstration of
    that blindness).  Raising here, before the eigensolver ever runs, is
    what closes that gap for the primary implementation.
    """
    materially_asymmetric = np.array([[1.0, 0.6, 0.2], [0.6, 1.0, 0.5], [0.9, 0.5, 1.0]])
    with pytest.raises(ValueError, match="symmetric"):
        effective_trial_count_from_correlation(materially_asymmetric)


def test_effective_trial_count_from_returns_shares_correlation_construction() -> None:
    """`effective_trial_count_from_returns` must route through the documented correlation builder."""
    rng = np.random.default_rng(31)
    returns = rng.normal(size=(50, 4))
    correlation = trial_return_correlation_matrix(returns)
    direct = effective_trial_count_from_correlation(correlation)
    via_returns = effective_trial_count_from_returns(returns)
    assert via_returns.effective_trial_count == pytest.approx(direct.effective_trial_count, abs=1e-12)
    assert via_returns.eigenvalues == direct.eigenvalues
