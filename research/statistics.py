"""Conservative, date-aware evidence statistics for research gates."""
from __future__ import annotations

from dataclasses import dataclass
import sys
from statistics import NormalDist
from typing import Any, Iterable

import numpy as np
import pandas as pd


def newey_west_tstat(series: Iterable[float], max_lags: int = 5) -> float:
    """
    Computes Newey-West autocorrelation-adjusted t-statistic for a 1D time series.
    """
    x = np.asarray(list(series), dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return 0.0

    mean_x = float(np.mean(x))
    dev = x - mean_x

    gamma_0 = float(np.mean(dev ** 2))
    if gamma_0 <= 0:
        return 0.0

    var_sum = gamma_0
    for lag in range(1, min(max_lags + 1, n)):
        weight = 1.0 - (lag / (max_lags + 1.0))
        gamma_lag = float(np.mean(dev[lag:] * dev[:-lag]))
        var_sum += 2.0 * weight * gamma_lag

    se = np.sqrt(max(var_sum, 1e-12) / n)
    return float(mean_x / se) if se > 0 else 0.0


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
    """Moving-block bootstrap CI for mean daily return, resampling dates not rows."""
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
    """A transparent conservative approximation to a deflated Sharpe test."""
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


deflated_sharpe_approximation = bonferroni_deflated_sharpe_approximation


@dataclass(frozen=True)
class EffectiveTrialCount:
    """Report-only effective search-multiplicity estimate (spec S11.4)."""

    raw_trial_count: int
    effective_trial_count: float
    eigenvalues: tuple[float, ...]
    n_observations: int | None
    diagnostic_only: bool = True


def _clip_eigenvalues(eigenvalues: np.ndarray, *, negative_eigenvalue_atol: float) -> np.ndarray:
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
    eigenvalues = np.linalg.eigvalsh((matrix + matrix.T) / 2.0)
    cleaned = _clip_eigenvalues(eigenvalues, negative_eigenvalue_atol=negative_eigenvalue_atol)
    total = float(cleaned.sum())
    if total <= 0.0:
        raise ValueError("correlation matrix has no positive spectral mass")
    probabilities = cleaned / total
    positive = probabilities > 0.0
    entropy = float(-np.sum(probabilities[positive] * np.log(probabilities[positive])))
    k_eff = float(np.exp(entropy))
    k_eff = min(max(k_eff, 1.0), float(k))
    return EffectiveTrialCount(
        raw_trial_count=k,
        effective_trial_count=k_eff,
        eigenvalues=tuple(float(v) for v in cleaned[::-1]),
        n_observations=None,
    )


def trial_return_correlation_matrix(trial_returns: Any) -> np.ndarray:
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
    corr = trial_return_correlation_matrix(trial_returns)
    result = effective_trial_count_from_correlation(corr, negative_eigenvalue_atol=negative_eigenvalue_atol)
    n_obs = int(np.asarray(trial_returns, dtype=float).shape[0])
    return EffectiveTrialCount(
        raw_trial_count=result.raw_trial_count,
        effective_trial_count=result.effective_trial_count,
        eigenvalues=result.eigenvalues,
        n_observations=n_obs,
    )
