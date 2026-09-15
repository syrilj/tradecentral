"""Causal market regime models, volatility environment, market structure, and transition hazards.

Theoretical Foundations:
- Strict Point-in-Time Causality (t <= T): zero forward-looking references.
- Rolling 252d Volatility Percentile: completely eliminates non-stationary expanding quantile drift.
- Market Structure: Lo-MacKinlay Overlapping Variance Ratio (q=5) and Ornstein-Uhlenbeck AR(1) half-life.
- Transition & Change-Point Hazards: Page's CUSUM innovation accumulator and BOCPD integration.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Optional, Sequence, Union

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Data Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VolatilityRegimeResult:
    """Trailing rolling percentile volatility environment output."""

    realized_volatility: pd.Series
    volatility_percentile: pd.Series
    volatility_state: pd.Series
    volatility_shock: pd.Series


@dataclass(frozen=True)
class MarketStructureResult:
    """Lo-MacKinlay Variance Ratio & OU Half-Life market structure output."""

    variance_ratio_5: pd.Series
    ou_half_life: pd.Series
    market_structure: pd.Series


@dataclass(frozen=True)
class TransitionRiskResult:
    """CUSUM and change-point transition hazard output."""

    cusum_pos: pd.Series
    cusum_neg: pd.Series
    cusum_score: pd.Series
    bocpd_break_prob: pd.Series
    transition_risk: pd.Series
    downside_hazard: pd.Series | None = None
    upside_expansion: pd.Series | None = None


# ---------------------------------------------------------------------------
# 1. Rolling Volatility Environment Model (Trailing 252d Percentiles)
# ---------------------------------------------------------------------------


def compute_rolling_volatility_regime(
    prices: pd.Series | pd.DataFrame,
    *,
    close_col: str = "close",
    vol_window: int = 20,
    percentile_window: int = 252,
    rvol_series: Optional[pd.Series] = None,
) -> VolatilityRegimeResult:
    """Compute trailing rolling 252-day percentile ranking of realized volatility.

    Classifies into 4 stationary tiers:
      - COMPRESSION_LOW: percentile < 0.25
      - NORMAL_MEDIUM: 0.25 <= percentile <= 0.75
      - ELEVATED_HIGH: 0.75 < percentile <= 0.90
      - VOLATILITY_SHOCK: percentile > 0.90 or RV > 2.5 * median_252(RV) or rvol > 3.0
    """
    if vol_window < 2 or percentile_window < 2:
        raise ValueError("vol_window and percentile_window must be >= 2")

    close = prices[close_col] if isinstance(prices, pd.DataFrame) else prices
    close = pd.to_numeric(close, errors="coerce").astype(float)
    if not close.index.is_monotonic_increasing or close.index.has_duplicates:
        raise ValueError("prices must have a unique ascending index")

    if (close <= 0).any():
        raise ValueError("close must be strictly positive and finite")

    # Causal log returns
    log_ret = np.log(close / close.shift(1))
    var_ret = log_ret.rolling(vol_window, min_periods=vol_window).var(ddof=1)
    rv = np.sqrt(np.maximum(0.0, var_ret * 252.0))

    # Rolling 252d percentile ranking: fraction of trailing window <= current RV
    n = len(rv)
    pctiles = np.full(n, np.nan, dtype=float)
    rv_arr = rv.to_numpy(dtype=float)

    for i in range(n):
        if not np.isfinite(rv_arr[i]):
            continue
        start_idx = max(0, i - percentile_window + 1)
        sub = rv_arr[start_idx : i + 1]
        valid_sub = sub[np.isfinite(sub)]
        if len(valid_sub) >= 2:
            if np.all(valid_sub == rv_arr[i]):
                pctiles[i] = 0.0 if rv_arr[i] <= 1e-6 else 0.5
            else:
                # Fraction of historical values <= current value
                pct = np.mean(valid_sub <= rv_arr[i])
                pctiles[i] = float(pct)
        elif len(valid_sub) == 1:
            pctiles[i] = 0.0 if rv_arr[i] <= 1e-6 else 0.5

    pct_s = pd.Series(pctiles, index=close.index)

    # Median 252d RV for spike detection
    med_rv = rv.rolling(percentile_window, min_periods=20).median()
    shock_cond = ((pct_s > 0.90) | (rv > 2.5 * med_rv)) & (rv > 1e-5)
    if rvol_series is not None:
        rvol_aligned = rvol_series.reindex(close.index).fillna(1.0)
        shock_cond = shock_cond | ((rvol_aligned > 3.0) & (rv > 1e-5))

    vol_state = pd.Series(pd.NA, index=close.index, dtype="string")
    valid_mask = pct_s.notna()

    vol_state.loc[valid_mask & (pct_s < 0.25)] = "COMPRESSION_LOW"
    vol_state.loc[valid_mask & (pct_s >= 0.25) & (pct_s <= 0.75)] = "NORMAL_MEDIUM"
    vol_state.loc[valid_mask & (pct_s > 0.75) & (pct_s <= 0.90)] = "ELEVATED_HIGH"
    vol_state.loc[valid_mask & shock_cond] = "VOLATILITY_SHOCK"

    shock_series = (shock_cond & valid_mask).astype(bool)

    return VolatilityRegimeResult(
        realized_volatility=rv,
        volatility_percentile=pct_s,
        volatility_state=vol_state,
        volatility_shock=shock_series,
    )


# ---------------------------------------------------------------------------
# 2. Market Structure Model (Lo-MacKinlay Variance Ratio & OU Half-Life)
# ---------------------------------------------------------------------------


def compute_variance_ratio(log_prices: np.ndarray, q: int = 5) -> float:
    """Compute Lo-MacKinlay overlapping Variance Ratio VR(q) = sigma^2(q) / sigma^2(1).

    VR > 1.15 indicates positive autocorrelation (trend persistence).
    VR < 0.85 indicates negative autocorrelation (mean reversion).
    """
    p = np.asarray(log_prices, dtype=float)
    p = p[np.isfinite(p)]
    n = len(p) - 1
    if n <= q:
        return 1.0

    # mu_hat
    mu_hat = (p[-1] - p[0]) / n

    # sigma^2(1)
    diff_1 = p[1:] - p[:-1] - mu_hat
    var_1 = np.sum(diff_1**2) / (n - 1)

    if var_1 <= 1e-12:
        return 1.0

    # Overlapping q-period returns
    # m = q * (n - q + 1) * (1 - q / n)
    m = float(q * (n - q + 1) * (1.0 - (q / float(n))))
    if m <= 0:
        return 1.0

    diff_q = p[q:] - p[:-q] - (q * mu_hat)
    var_q = np.sum(diff_q**2) / m

    vr = float(var_q / var_1)
    return max(0.0, vr)


def compute_ou_half_life(prices: np.ndarray, window: int = 30) -> float:
    """Estimate Ornstein-Uhlenbeck mean-reversion half-life t_{1/2} = ln(2) / theta via AR(1).

    Returns half-life bounded in [1.0, 100.0] bars.
    """
    p = np.asarray(prices, dtype=float)
    p = p[np.isfinite(p)]
    if len(p) < 4:
        return 100.0

    sub = p[-window:] if len(p) >= window else p
    mean_p = np.mean(sub)
    dev = sub - mean_p
    dev_lag = dev[:-1]
    dev_curr = dev[1:]

    denom = np.sum(dev_lag**2)
    if denom <= 1e-12:
        return 100.0

    beta = np.sum(dev_lag * dev_curr) / denom
    if beta <= 0.0:
        return 1.0
    if beta >= 1.0:
        return 100.0

    # beta = exp(-theta) -> theta = -ln(beta) -> t_1/2 = ln(2) / theta
    theta = -math.log(beta)
    if theta <= 1e-6:
        return 100.0
    half_life = math.log(2.0) / theta
    return min(100.0, max(1.0, float(half_life)))


def compute_market_structure(
    prices: pd.Series | pd.DataFrame,
    *,
    close_col: str = "close",
    vr_window: int = 60,
    vr_lag: int = 5,
    ou_window: int = 30,
    kalman_z_series: Optional[pd.Series] = None,
) -> MarketStructureResult:
    """Compute rolling Lo-MacKinlay Variance Ratio (q=5) and OU half-life.

    Classifies into:
      - TRENDING: VR(5) > 1.15 and (|z_v| > 0.8 or t_{1/2} > 20.0)
      - MEAN_REVERTING: VR(5) < 0.85 and t_{1/2} <= 15.0
      - RANGE_BOUND: Otherwise
    """
    close = prices[close_col] if isinstance(prices, pd.DataFrame) else prices
    close = pd.to_numeric(close, errors="coerce").astype(float)
    if not close.index.is_monotonic_increasing or close.index.has_duplicates:
        raise ValueError("prices must have a unique ascending index")

    if (close <= 0).any():
        raise ValueError("close must be strictly positive and finite")

    log_p = np.log(close).to_numpy(dtype=float)
    raw_p = close.to_numpy(dtype=float)
    n = len(close)

    vr_arr = np.full(n, np.nan, dtype=float)
    ou_arr = np.full(n, np.nan, dtype=float)
    struct_arr = np.empty(n, dtype=object)

    z_vals = (
        kalman_z_series.reindex(close.index).to_numpy(dtype=float)
        if kalman_z_series is not None
        else np.zeros(n, dtype=float)
    )

    for i in range(n):
        if i < vr_lag + 2:
            vr_arr[i] = 1.0
            ou_arr[i] = 100.0
            struct_arr[i] = "RANGE_BOUND"
            continue

        start_vr = max(0, i - vr_window + 1)
        sub_log = log_p[start_vr : i + 1]
        vr_val = compute_variance_ratio(sub_log, q=vr_lag)
        vr_arr[i] = vr_val

        start_ou = max(0, i - ou_window + 1)
        sub_raw = raw_p[start_ou : i + 1]
        ou_val = compute_ou_half_life(sub_raw, window=ou_window)
        ou_arr[i] = ou_val

        z_i = z_vals[i] if np.isfinite(z_vals[i]) else 0.0

        if vr_val > 1.15 and (abs(z_i) > 0.8 or ou_val > 20.0):
            struct_arr[i] = "TRENDING"
        elif vr_val < 0.85 and ou_val <= 15.0:
            struct_arr[i] = "MEAN_REVERTING"
        else:
            struct_arr[i] = "RANGE_BOUND"

    return MarketStructureResult(
        variance_ratio_5=pd.Series(vr_arr, index=close.index),
        ou_half_life=pd.Series(ou_arr, index=close.index),
        market_structure=pd.Series(struct_arr, index=close.index, dtype="string"),
    )


# ---------------------------------------------------------------------------
# 3. Transition & Change-Point Hazard Model (CUSUM & BOCPD)
# ---------------------------------------------------------------------------


def compute_cusum_transition_risk(
    returns: pd.Series | np.ndarray,
    *,
    vol_window: int = 20,
    k: float = 0.5,
    h: float = 4.0,
    bocpd_break_prob: Optional[pd.Series] = None,
    vol_shock_mask: Optional[pd.Series] = None,
) -> TransitionRiskResult:
    """Compute Page's CUSUM innovation accumulator and composite transition hazard T_risk in [0.0, 1.0]."""
    if isinstance(returns, pd.Series):
        r_s = pd.to_numeric(returns, errors="coerce").astype(float)
        idx = returns.index
    else:
        r_s = pd.Series(returns, dtype=float)
        idx = r_s.index

    mean_r = r_s.rolling(vol_window, min_periods=vol_window).mean()
    std_r = r_s.rolling(vol_window, min_periods=vol_window).std(ddof=1)
    safe_std = std_r.where(std_r > 1e-6, 1e-6)

    z_r = (r_s - mean_r) / safe_std
    z_arr = z_r.fillna(0.0).to_numpy(dtype=float)

    n = len(z_arr)
    s_pos = np.zeros(n, dtype=float)
    s_neg = np.zeros(n, dtype=float)
    t_cusum = np.zeros(n, dtype=float)

    for i in range(1, n):
        s_pos[i] = max(0.0, s_pos[i - 1] + z_arr[i] - k)
        s_neg[i] = max(0.0, s_neg[i - 1] - z_arr[i] - k)
        max_s = max(s_pos[i], s_neg[i])
        t_cusum[i] = min(1.0, max_s / h)

    s_pos_s = pd.Series(s_pos, index=idx)
    s_neg_s = pd.Series(s_neg, index=idx)
    t_cusum_s = pd.Series(t_cusum, index=idx)

    bocpd_s = (
        bocpd_break_prob.reindex(idx).fillna(0.0)
        if bocpd_break_prob is not None
        else pd.Series(0.0, index=idx)
    )

    # Directional volatility shock decoupling:
    # A vol shock with negative return / negative CUSUM is a downside transition hazard.
    # A vol shock with positive return / positive CUSUM is an upside breakout expansion.
    shock_is_down = (r_s < 0) | (s_neg_s > s_pos_s)
    shock_is_up = (r_s > 0) & (s_pos_s >= s_neg_s)

    down_shock_penalty = (
        (vol_shock_mask.reindex(idx).fillna(False) & shock_is_down).astype(float) * 0.85
        if vol_shock_mask is not None
        else pd.Series(0.0, index=idx)
    )
    up_shock_bonus = (
        (vol_shock_mask.reindex(idx).fillna(False) & shock_is_up).astype(float) * 0.85
        if vol_shock_mask is not None
        else pd.Series(0.0, index=idx)
    )

    t_down_s = s_neg_s / float(h)
    t_up_s = s_pos_s / float(h)
    downside_hazard = pd.concat([t_down_s, bocpd_s, down_shock_penalty], axis=1).max(axis=1).clip(lower=0.0, upper=1.0)
    upside_expansion = pd.concat([t_up_s, up_shock_bonus], axis=1).max(axis=1).clip(lower=0.0, upper=1.0)

    t_risk = pd.concat([t_cusum_s, bocpd_s, down_shock_penalty], axis=1).max(axis=1)
    t_risk = t_risk.clip(lower=0.0, upper=1.0)

    return TransitionRiskResult(
        cusum_pos=s_pos_s,
        cusum_neg=s_neg_s,
        cusum_score=t_cusum_s,
        bocpd_break_prob=bocpd_s,
        transition_risk=t_risk,
        downside_hazard=downside_hazard,
        upside_expansion=upside_expansion,
    )


# ---------------------------------------------------------------------------
# Legacy Backward Compatibility Wrappers
# ---------------------------------------------------------------------------


def classify_regimes(
    prices: pd.Series | pd.DataFrame,
    *,
    close_col: str = "close",
    volatility_window: int = 20,
    trend_window: int = 60,
    bear_drawdown: float = -0.15,
) -> pd.DataFrame:
    """Return trailing-only volatility, trend, and drawdown regime labels."""
    if volatility_window < 2 or trend_window < 2 or bear_drawdown >= 0:
        raise ValueError("invalid causal regime configuration")
    close = prices[close_col] if isinstance(prices, pd.DataFrame) else prices
    close = pd.to_numeric(close, errors="coerce").astype(float)
    if not close.index.is_monotonic_increasing or close.index.has_duplicates:
        raise ValueError("prices must have a unique ascending index")
    returns = close.pct_change(fill_method=None)
    volatility = returns.rolling(volatility_window, min_periods=volatility_window).std(ddof=1)
    low, high = (
        volatility.expanding(min_periods=volatility_window).quantile(1 / 3),
        volatility.expanding(min_periods=volatility_window).quantile(2 / 3),
    )
    volatility_regime = pd.Series(pd.NA, index=close.index, dtype="string")
    valid_vol = volatility.notna() & low.notna() & high.notna()
    volatility_regime.loc[valid_vol & (volatility <= low)] = "LOW"
    volatility_regime.loc[valid_vol & (volatility > low) & (volatility <= high)] = "MEDIUM"
    volatility_regime.loc[valid_vol & (volatility > high)] = "HIGH"

    ma = close.rolling(trend_window, min_periods=trend_window).mean()
    trend_regime = pd.Series(pd.NA, index=close.index, dtype="string")
    trend_regime.loc[ma.notna() & (close > ma)] = "UP"
    trend_regime.loc[ma.notna() & (close < ma)] = "DOWN"
    trend_regime.loc[ma.notna() & (close == ma)] = "FLAT"
    drawdown = close.div(close.cummax()).sub(1.0)
    bear_market = (drawdown <= bear_drawdown).astype("boolean")
    bear_market.loc[close.isna()] = pd.NA
    return pd.DataFrame(
        {
            "realized_volatility": volatility,
            "volatility_regime": volatility_regime,
            "trend_regime": trend_regime,
            "drawdown": drawdown,
            "bear_market": bear_market,
        },
        index=close.index,
    )


def slice_by_regime(
    records: pd.DataFrame,
    regime_columns: Iterable[str] = ("volatility_regime", "trend_regime", "bear_market"),
) -> dict[tuple[object, ...], pd.DataFrame]:
    """Partition evidence rows by the selected regime columns without mutation."""
    cols = tuple(regime_columns)
    missing = set(cols).difference(records.columns)
    if missing:
        raise KeyError(f"missing regime columns: {sorted(missing)}")
    return {
        key if isinstance(key, tuple) else (key,): group.copy()
        for key, group in records.groupby(list(cols), dropna=False, sort=True)
    }


def performance_by_regime(
    records: pd.DataFrame,
    *,
    return_col: str = "net_return",
    regime_columns: Iterable[str] = ("volatility_regime", "trend_regime", "bear_market"),
) -> pd.DataFrame:
    """Summarise observations, mean return, and win rate for each regime slice."""
    if return_col not in records:
        raise KeyError(f"missing return column: {return_col}")
    cols = list(regime_columns)
    if not cols:
        raise ValueError("at least one regime column is required")
    values = pd.to_numeric(records[return_col], errors="coerce")
    frame = records.loc[:, cols].copy()
    frame[return_col] = values
    grouped = frame.groupby(cols, dropna=False, sort=True)[return_col]
    return (
        grouped.agg(n="count", mean_return="mean", median_return="median")
        .assign(win_rate=grouped.apply(lambda x: float((x > 0).mean()) if len(x) else np.nan))
        .reset_index()
    )
