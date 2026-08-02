"""Conservative, date-aware evidence statistics for research gates."""
from __future__ import annotations

from dataclasses import dataclass
import sys
from statistics import NormalDist
from typing import Any, Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BootstrapCI:
    estimate: float
    lower: float
    upper: float
    confidence: float
    n_dates: int
    block_size: int
    n_bootstrap: int


def date_block_bootstrap_ci(
    returns: Iterable[float],
    dates: Iterable[object],
    *,
    confidence: float = 0.95,
    block_size: int = 5,
    n_bootstrap: int = 2_000,
    seed: int = 0,
) -> BootstrapCI:
    """Moving-block bootstrap CI for mean daily return, resampling dates not rows.

    Multiple symbols decided on one date are aggregated before resampling, which
    avoids pretending correlated cross-sectional positions are independent.
    """
    if not (0.0 < confidence < 1.0):
        raise ValueError("confidence must be in (0, 1)")
    if block_size < 1 or n_bootstrap < 1:
        raise ValueError("block_size and n_bootstrap must be positive")
    values = np.asarray(list(returns), dtype=float)
    date_index = pd.to_datetime(list(dates), errors="coerce")
    if values.size != date_index.size:
        raise ValueError("returns and dates must have equal lengths")
    usable = np.isfinite(values) & ~pd.isna(date_index)
    if not usable.any():
        raise ValueError("at least one finite dated return is required")
    frame = pd.DataFrame({"date": date_index[usable].normalize(), "return": values[usable]})
    daily = frame.groupby("date", sort=True)["return"].mean().to_numpy(dtype=float)
    n_dates = int(daily.size)
    if n_dates < 2:
        raise ValueError("at least two unique dates are required for bootstrap inference")
    rng = np.random.default_rng(seed)
    samples = np.empty(n_bootstrap, dtype=float)
    starts_max = n_dates if n_dates > block_size else 1
    for sample_idx in range(n_bootstrap):
        chosen: list[float] = []
        while len(chosen) < n_dates:
            start = int(rng.integers(starts_max))
            chosen.extend(daily[(start + offset) % n_dates] for offset in range(block_size))
        samples[sample_idx] = float(np.mean(chosen[:n_dates]))
    alpha = (1.0 - confidence) / 2.0
    return BootstrapCI(
        estimate=float(np.mean(daily)),
        lower=float(np.quantile(samples, alpha)),
        upper=float(np.quantile(samples, 1.0 - alpha)),
        confidence=confidence,
        n_dates=n_dates,
        block_size=block_size,
        n_bootstrap=n_bootstrap,
    )


@dataclass(frozen=True)
class DeflatedSharpeApproximation:
    """Bonferroni search-adjusted lower confidence bound for annualized Sharpe."""

    observed_sharpe: float
    lower_bound_sharpe: float
    daily_sharpe: float
    trial_count: int
    n_observations: int
    confidence: float
    critical_z: float


def bonferroni_deflated_sharpe_approximation(
    returns: Iterable[float],
    *,
    trial_count: int,
    periods_per_year: int = 252,
    confidence: float = 0.95,
) -> DeflatedSharpeApproximation:
    """A transparent conservative approximation to a deflated Sharpe test.

    This is *not* the full Bailey--Lopez de Prado DSR.  It applies a one-sided
    Bonferroni family-wise correction across recorded trials to an IID standard
    error, so the result is deliberately named as an approximation.  Serial
    dependence should additionally be assessed with ``date_block_bootstrap_ci``.
    """
    if trial_count < 1 or periods_per_year < 1 or not (0.0 < confidence < 1.0):
        raise ValueError("invalid trial_count, periods_per_year, or confidence")
    values = np.asarray(list(returns), dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 2:
        raise ValueError("at least two finite returns are required")
    sigma = float(np.std(values, ddof=1))
    if sigma <= 0.0:
        raise ValueError("returns must have non-zero sample volatility")
    daily_sharpe = float(np.mean(values) / sigma)
    observed = daily_sharpe * float(np.sqrt(periods_per_year))
    alpha_per_trial = (1.0 - confidence) / trial_count
    critical_z = NormalDist().inv_cdf(1.0 - alpha_per_trial)
    lower_daily = daily_sharpe - critical_z / float(np.sqrt(values.size))
    return DeflatedSharpeApproximation(
        observed_sharpe=observed,
        lower_bound_sharpe=lower_daily * float(np.sqrt(periods_per_year)),
        daily_sharpe=daily_sharpe,
        trial_count=trial_count,
        n_observations=int(values.size),
        confidence=confidence,
        critical_z=float(critical_z),
    )


# A concise alias for callers that already disclose the approximation in reports.
deflated_sharpe_approximation = bonferroni_deflated_sharpe_approximation


# ---------------------------------------------------------------------------
# Effective trial count (architecture spec S11.4) -- REPORT-ONLY diagnostic.
# ---------------------------------------------------------------------------
#
# K_eff estimates how many *independent* trials a correlated search behaves
# like:
#
#     K_eff = exp( -sum_j p_j * log(p_j) ),   p_j = lambda_j / sum_k lambda_k
#
# where lambda_j are the eigenvalues of the trial-return correlation matrix R
# after clipping tiny negative floating-point noise to zero.  This is the
# exponential of the Shannon entropy of R's normalized eigenvalue spectrum:
# a fully diversified (orthogonal) search of K trials has a flat spectrum
# and K_eff == K; a fully redundant (identical) search collapses to a single
# nonzero eigenvalue and K_eff == 1.  K_eff <= raw_trial_count always holds.
#
# THIS SECTION IS DIAGNOSTIC ONLY.  Never pass ``effective_trial_count``
# anywhere ``bonferroni_deflated_sharpe_approximation`` expects
# ``trial_count``.  Substituting K_eff for the raw, pre-registered trial
# count would relax the multiple-testing correction above: a smaller
# ``trial_count`` produces a smaller ``critical_z`` and therefore a *higher*,
# easier-to-clear ``lower_bound_sharpe``.  That is the wrong direction of
# error for a project whose two retracted GO calls (``GATE_XS3_RESULT.md``,
# ``GATE_PEAD_RESULT.md``) were both false positives from under-corrected
# search.  Continue gating on the raw trial count; report K_eff alongside it
# purely for human review of how much of the raw count is actually
# independent.


@dataclass(frozen=True)
class EffectiveTrialCount:
    """Report-only effective search-multiplicity estimate (spec S11.4).

    ``effective_trial_count`` (K_eff) is a *diagnostic*, not a gating input.
    It must never be substituted for ``trial_count`` in
    :func:`bonferroni_deflated_sharpe_approximation` -- see the module note
    above this class for why that would silently loosen the gate.
    ``raw_trial_count`` is, and must remain, the value that gates.
    """

    raw_trial_count: int
    effective_trial_count: float
    eigenvalues: tuple[float, ...]
    n_observations: int | None
    diagnostic_only: bool = True


def _clip_eigenvalues(eigenvalues: np.ndarray, *, negative_eigenvalue_atol: float) -> np.ndarray:
    """Zero out floating-point negative-eigenvalue noise; refuse real breaks.

    A trial-return correlation matrix is mathematically positive
    semi-definite, so any negative eigenvalue in an exact computation would
    be zero; a small negative value is expected floating-point noise from
    the eigensolver.  A *materially* negative eigenvalue instead means the
    supplied matrix was not a valid correlation matrix -- a caller bug worth
    raising on rather than silently absorbing into the estimate.
    """
    magnitude = float(np.max(np.abs(eigenvalues))) if eigenvalues.size else 0.0
    floor = -negative_eigenvalue_atol * max(1.0, magnitude)
    if float(np.min(eigenvalues)) < floor:
        raise ValueError(
            "correlation matrix has a materially negative eigenvalue and is not "
            "positive semi-definite; this is not floating-point noise"
        )
    return np.clip(eigenvalues, 0.0, None)


def effective_trial_count_from_correlation(
    correlation: Any,
    *,
    negative_eigenvalue_atol: float = 1e-8,
) -> EffectiveTrialCount:
    """K_eff (spec S11.4) from a trial-return correlation matrix R.  Report-only.

    ``correlation`` must be square with one row/column per trial.  Tiny
    negative eigenvalues from floating-point estimation noise are clipped to
    zero before the entropy calculation (see ``_clip_eigenvalues``); a
    materially negative eigenvalue raises instead of silently producing a
    nonsensical result.  ``K_eff`` is bounded in ``[1, raw_trial_count]`` by
    construction: it is the exponential of the entropy of a probability
    distribution over at most ``raw_trial_count`` outcomes, and entropy of
    such a distribution is itself bounded in ``[0, log(raw_trial_count)]``.
    """
    if not (np.isfinite(negative_eigenvalue_atol) and negative_eigenvalue_atol >= 0.0):
        raise ValueError("negative_eigenvalue_atol must be finite and non-negative")
    matrix = np.asarray(correlation, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("correlation must be a square 2D matrix")
    k = matrix.shape[0]
    if k < 1:
        raise ValueError("correlation matrix must have at least one trial")
    if not np.isfinite(matrix).all():
        raise ValueError("correlation matrix must be finite")
    if k > 1:
        scale = max(1.0, float(np.max(np.abs(matrix))))
        if float(np.max(np.abs(matrix - matrix.T))) > 1e-6 * scale:
            raise ValueError("correlation matrix must be symmetric")
    # Symmetrizing before the symmetric eigensolver only cancels asymmetry
    # that is itself floating-point noise -- the check above already refused
    # anything larger.
    eigenvalues = np.linalg.eigvalsh((matrix + matrix.T) / 2.0)
    cleaned = _clip_eigenvalues(eigenvalues, negative_eigenvalue_atol=negative_eigenvalue_atol)
    total = float(cleaned.sum())
    if total <= 0.0:
        raise ValueError("correlation matrix has no positive spectral mass")
    probabilities = cleaned / total
    positive = probabilities > 0.0
    entropy = float(-np.sum(probabilities[positive] * np.log(probabilities[positive])))
    k_eff = float(np.exp(entropy))
    # The [1, k] bound is a mathematical property of this construction (see
    # docstring); clipping here only absorbs float roundoff at the boundary
    # (e.g. 10.000000000000002 -> 10.0), it cannot mask a real estimation
    # bug that would show up as a materially wrong value elsewhere in range.
    k_eff = min(max(k_eff, 1.0), float(k))
    return EffectiveTrialCount(
        raw_trial_count=k,
        effective_trial_count=k_eff,
        eigenvalues=tuple(float(v) for v in cleaned[::-1]),
        n_observations=None,
    )


def trial_return_correlation_matrix(trial_returns: Any) -> np.ndarray:
    """Build a well-defined correlation matrix from a raw trial-return panel.

    ``trial_returns`` is a dense ``(n_observations, n_trials)`` matrix: one
    column per trial's return series, aligned on the same observation index
    (this is independent of how or whether those series are persisted --
    pass any array-like with that shape).  A constant (zero-variance) trial
    column has an exactly-zero covariance with every other column regardless
    of the other column's values, so it is recorded as uncorrelated with
    every other trial; its diagonal entry is fixed at 1.0 like any other
    trial's, since a correlation matrix's diagonal is always 1 by
    definition. This keeps the matrix well-defined (finite, valid for
    eigen-decomposition) instead of propagating the NaN that ``0/0`` would
    otherwise produce.
    """
    values = np.asarray(trial_returns, dtype=float)
    if values.ndim != 2:
        raise ValueError("trial_returns must be a 2D (n_observations, n_trials) matrix")
    n_obs, n_trials = values.shape
    if n_trials < 1:
        raise ValueError("trial_returns must have at least one trial column")
    if n_obs < 1:
        raise ValueError("trial_returns must contain at least one observation")
    if not np.isfinite(values).all():
        raise ValueError("trial_returns must be finite")
    if n_trials == 1:
        # A single trial's correlation with itself is 1 by definition; no
        # variance estimate is needed to know K_eff is trivially 1.
        return np.ones((1, 1))
    if n_obs < 2:
        raise ValueError("at least two observations are required to estimate a correlation matrix")
    demeaned = values - values.mean(axis=0, keepdims=True)
    cov = (demeaned.T @ demeaned) / float(n_obs - 1)
    std = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    denom = np.outer(std, std)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.where(denom > 0.0, cov / denom, 0.0)
    np.fill_diagonal(corr, 1.0)
    return corr


def effective_trial_count_from_returns(
    trial_returns: Any,
    *,
    negative_eigenvalue_atol: float = 1e-8,
) -> EffectiveTrialCount:
    """K_eff (spec S11.4) from a raw ``(n_observations, n_trials)`` return panel.

    Convenience wrapper around :func:`trial_return_correlation_matrix` and
    :func:`effective_trial_count_from_correlation`.  Report-only -- see the
    module note above :class:`EffectiveTrialCount`.
    """
    corr = trial_return_correlation_matrix(trial_returns)
    result = effective_trial_count_from_correlation(corr, negative_eigenvalue_atol=negative_eigenvalue_atol)
    n_obs = int(np.asarray(trial_returns, dtype=float).shape[0])
    return EffectiveTrialCount(
        raw_trial_count=result.raw_trial_count,
        effective_trial_count=result.effective_trial_count,
        eigenvalues=result.eigenvalues,
        n_observations=n_obs,
    )
