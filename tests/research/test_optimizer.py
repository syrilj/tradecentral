"""Tests for edge.research.optimizer -- cost-aware weight formation.

The headline claim this module makes over the status quo (form weights, THEN
charge turnover in `simulate_long_short`) is that putting the cost inside the
objective actually reduces realized turnover as the penalty is dialed up.
`test_turnover_penalty_sweep_is_monotonic_in_realized_turnover` is the test
that proves that claim using the repo's own audited accounting primitive --
if it fails, this module has no reason to exist (see optimizer.py's module
docstring).

`test_covariance_uses_no_future_data` is the anti-lookahead test for this
module's own causality boundary (see optimize_panel's docstring). It was
manually verified during development to FAIL when the trailing window is
replaced with a centred window (`returns.iloc[i - w // 2 : i + w // 2 + 1]`)
-- i.e. it is not vacuously passing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.optimizer import OptimizerConfig, optimize_panel, optimize_weights
from edge.research.portfolio import simulate_long_short


def _close_panel(n_dates: int, n_syms: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n_dates)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    rets = pd.DataFrame(rng.normal(0.0, 0.015, size=(n_dates, n_syms)), index=dates, columns=syms)
    close = 100.0 * (1.0 + rets).cumprod()
    return close


def _noisy_alpha_panel(close: pd.DataFrame, *, seed: int, alpha_scale: float = 0.003) -> pd.DataFrame:
    """A synthetic alpha with a slowly-varying per-name component plus daily
    noise of comparable magnitude -- realistic enough that a turnover-cost
    term at realistic `cost_per_side` scale actually competes with it, so a
    monotonicity sweep has something to bite on."""
    rng = np.random.default_rng(seed)
    n_dates, n_syms = close.shape
    base = rng.normal(0.0, alpha_scale, size=n_syms)
    noise = rng.normal(0.0, alpha_scale, size=(n_dates, n_syms))
    values = base[None, :] + noise
    return pd.DataFrame(values, index=close.index, columns=close.columns)


def test_turnover_penalty_zero_concentrates_on_top_bottom_alpha() -> None:
    """No turnover cost, no previous position, diagonal (uncorrelated) risk,
    generous caps: the sign of each solved weight must match the sign of its
    alpha, and the largest-|alpha| name must get the largest-magnitude
    weight on its side."""
    names = [f"S{i:02d}" for i in range(8)]
    alpha = pd.Series([0.05, 0.03, 0.01, 0.001, -0.001, -0.01, -0.03, -0.06], index=names)
    covariance = pd.DataFrame(np.eye(8) * 0.0004, index=names, columns=names)
    config = OptimizerConfig(
        risk_aversion=1.0, turnover_penalty=0.0, cost_per_side=0.0,
        max_weight=1.0, leverage=100.0, dollar_neutral=False,
    )
    w = optimize_weights(alpha=alpha, prev_weights=None, covariance=covariance, config=config)

    assert np.sign(w["S00"]) == 1  # largest positive alpha
    assert np.sign(w["S07"]) == -1  # largest negative alpha
    assert w["S00"] > w["S01"] > w["S02"] > 0
    assert w["S07"] < w["S06"] < w["S05"] < 0
    assert w["S00"] == pytest.approx(w.abs().max())


def test_turnover_penalty_sweep_is_monotonic_in_realized_turnover() -> None:
    """The headline test. Sweep turnover_penalty, run each resulting weight
    panel through the REAL simulate_long_short, and assert realized annual
    turnover is non-increasing as the penalty rises."""
    close = _close_panel(n_dates=160, n_syms=10, seed=1)
    alpha = _noisy_alpha_panel(close, seed=2)

    turnovers = []
    for penalty in (0.0, 1.0, 5.0, 25.0):
        config = OptimizerConfig(
            risk_aversion=5.0, turnover_penalty=penalty,
            max_weight=0.20, leverage=1.0, dollar_neutral=True,
        )
        long_w, short_w = optimize_panel(
            alpha=alpha, close=close, config=config, covariance_window=40, rebalance_every=1,
        )
        result = simulate_long_short(
            long_weights=long_w, short_weights=short_w, close=close, execution_lag=1,
        )
        turnovers.append(result.annual_turnover)

    for earlier, later in zip(turnovers, turnovers[1:]):
        assert later <= earlier + 1e-9, f"turnover rose as penalty increased: {turnovers}"
    # Not just flat-zero-everywhere: the unpenalized end must actually trade.
    assert turnovers[0] > turnovers[-1]


def test_constraints_hold_at_a_single_bar() -> None:
    names = [f"S{i:02d}" for i in range(12)]
    rng = np.random.default_rng(3)
    alpha = pd.Series(rng.normal(0.0, 0.01, size=12), index=names)
    covariance = pd.DataFrame(rng.normal(size=(12, 12)), index=names, columns=names)
    covariance = covariance @ covariance.T / 12.0  # a valid PSD covariance
    config = OptimizerConfig(
        risk_aversion=2.0, turnover_penalty=1.0, max_weight=0.05, leverage=0.6, dollar_neutral=True,
    )
    w = optimize_weights(alpha=alpha, prev_weights=None, covariance=covariance, config=config)

    tol = 1e-6
    assert (w.abs() <= config.max_weight + tol).all()
    assert w.abs().sum() <= config.leverage + tol
    assert abs(w.sum()) < tol


def test_constraints_hold_across_a_panel() -> None:
    close = _close_panel(n_dates=80, n_syms=9, seed=4)
    alpha = _noisy_alpha_panel(close, seed=5)
    config = OptimizerConfig(
        risk_aversion=2.0, turnover_penalty=2.0, max_weight=0.04, leverage=0.5, dollar_neutral=True,
    )
    long_w, short_w = optimize_panel(alpha=alpha, close=close, config=config, covariance_window=20)

    net = long_w - short_w
    tol = 1e-6
    assert (net.abs() <= config.max_weight + tol).to_numpy().all()
    assert ((long_w + short_w).sum(axis=1) <= config.leverage + tol).all()
    assert (net.sum(axis=1).abs() < tol).all()


def test_covariance_uses_no_future_data() -> None:
    """Anti-lookahead test for optimize_panel's own causality boundary.

    Mutating `close` strictly AFTER bar i must not change the weight solved
    at bar i, because the covariance feeding that solve is a trailing window
    ending at i. Verified by hand during development to fail if the window
    is replaced with a centred one.
    """
    close = _close_panel(n_dates=120, n_syms=8, seed=6)
    alpha = _noisy_alpha_panel(close, seed=7)
    config = OptimizerConfig(risk_aversion=3.0, turnover_penalty=1.0, max_weight=0.15, leverage=1.0)

    long_before, short_before = optimize_panel(alpha=alpha, close=close, config=config, covariance_window=30)

    i = 60
    mutated = close.copy()
    rng = np.random.default_rng(99)
    shock = 1.0 + rng.normal(0.0, 0.5, size=mutated.shape[1])
    mutated.iloc[i + 1 :] = mutated.iloc[i + 1 :] * shock  # strictly after bar i

    long_after, short_after = optimize_panel(alpha=alpha, close=mutated, config=config, covariance_window=30)

    pd.testing.assert_series_equal(long_before.iloc[i], long_after.iloc[i], check_exact=True)
    pd.testing.assert_series_equal(short_before.iloc[i], short_after.iloc[i], check_exact=True)
    # Sanity: the mutation must actually have changed *something* downstream
    # (a later bar's covariance/weight), otherwise this test would pass
    # trivially because the mutation had no effect on the panel at all.
    assert not long_before.iloc[i + 5 :].equals(long_after.iloc[i + 5 :])


def test_rebalance_every_reduces_turnover() -> None:
    close = _close_panel(n_dates=150, n_syms=8, seed=8)
    alpha = _noisy_alpha_panel(close, seed=9)
    config = OptimizerConfig(risk_aversion=3.0, turnover_penalty=1.0, max_weight=0.15, leverage=1.0)

    long1, short1 = optimize_panel(alpha=alpha, close=close, config=config, covariance_window=30, rebalance_every=1)
    long5, short5 = optimize_panel(alpha=alpha, close=close, config=config, covariance_window=30, rebalance_every=5)

    res1 = simulate_long_short(long_weights=long1, short_weights=short1, close=close, execution_lag=1)
    res5 = simulate_long_short(long_weights=long5, short_weights=short5, close=close, execution_lag=1)

    assert res5.annual_turnover < res1.annual_turnover


def test_solver_failure_raises() -> None:
    """A solver that cannot run at all (unknown solver name) must raise --
    not fall back to previous weights or zeros. Constraint infeasibility
    cannot be constructed from this module's own constraint set (the zero
    vector always satisfies ||w||_1 <= leverage, |w_i| <= max_weight, and
    sum(w) == 0 simultaneously, since leverage/max_weight are upper bounds
    with no lower-bound counterpart), so an unusable solver is the
    deterministic way to exercise the raise path."""
    names = [f"S{i:02d}" for i in range(5)]
    alpha = pd.Series([0.02, 0.01, 0.0, -0.01, -0.02], index=names)
    config = OptimizerConfig(solver="NOT_A_REAL_SOLVER")
    with pytest.raises(RuntimeError, match="NOT_A_REAL_SOLVER"):
        optimize_weights(alpha=alpha, prev_weights=None, covariance=None, config=config)


def test_all_nan_alpha_raises() -> None:
    names = [f"S{i:02d}" for i in range(5)]
    alpha = pd.Series([np.nan] * 5, index=names)
    with pytest.raises(ValueError, match="NaN"):
        optimize_weights(alpha=alpha, prev_weights=None, covariance=None, config=OptimizerConfig())


def test_zero_variance_alpha_raises() -> None:
    names = [f"S{i:02d}" for i in range(5)]
    alpha = pd.Series([0.01] * 5, index=names)
    with pytest.raises(ValueError, match="variance"):
        optimize_weights(alpha=alpha, prev_weights=None, covariance=None, config=OptimizerConfig())


def test_output_frames_are_directly_accepted_by_simulate_long_short() -> None:
    close = _close_panel(n_dates=90, n_syms=7, seed=10)
    alpha = _noisy_alpha_panel(close, seed=11)
    config = OptimizerConfig(risk_aversion=2.0, turnover_penalty=1.0, max_weight=0.20, leverage=1.0)
    long_w, short_w = optimize_panel(alpha=alpha, close=close, config=config, covariance_window=20)

    # No reshaping, renaming, or reindexing before this call -- shape/columns
    # match close exactly, and short_weights holds positive magnitudes.
    assert long_w.index.equals(close.index) and short_w.index.equals(close.index)
    assert set(long_w.columns) == set(close.columns) and set(short_w.columns) == set(close.columns)
    assert (short_w >= 0).to_numpy().all()

    result = simulate_long_short(long_weights=long_w, short_weights=short_w, close=close, execution_lag=1)
    assert np.isfinite(result.annual_turnover)
    assert result.n_bars == len(close.index)


def test_covariance_none_drops_risk_term_not_identity() -> None:
    """covariance=None must genuinely omit the risk term, not silently act
    like an identity risk matrix (which would penalize concentration and
    shrink weights even with covariance=None)."""
    names = [f"S{i:02d}" for i in range(6)]
    alpha = pd.Series([0.05, 0.03, 0.01, -0.01, -0.03, -0.05], index=names)
    config = OptimizerConfig(
        risk_aversion=50.0, turnover_penalty=0.0, max_weight=1.0, leverage=100.0, dollar_neutral=False,
    )
    w_no_risk = optimize_weights(alpha=alpha, prev_weights=None, covariance=None, config=config)

    identity = pd.DataFrame(np.eye(6), index=names, columns=names)
    w_identity_risk = optimize_weights(alpha=alpha, prev_weights=None, covariance=identity, config=config)

    # With a high risk_aversion, an identity risk term would shrink weights
    # substantially relative to no risk term at all.
    assert w_no_risk.abs().sum() > w_identity_risk.abs().sum()
