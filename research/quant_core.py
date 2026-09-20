"""Shared math layer for the quant research tabs.

Implements the pinned API of spec section 1 in
``docs/QUANT_RESEARCH_TABS_SPEC.md``: pure numpy/pandas functions only --
no FastAPI imports, no network, no file I/O, no side effects.

Existing code is reused, not copied: the causal volatility helpers
``realized_volatility`` / ``ewma_volatility`` are re-exported from
``research.vol_targeting`` (they already enforce trailing windows and
``min_periods`` warm-up semantics).

Everything here is causal by construction: every rolling quantity at bar
``t`` is a function of bars ``<= t`` only.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .vol_targeting import ewma_volatility, realized_volatility

ANNUAL = 252

# MacKinnon response-surface critical values for the Engle-Granger two-step
# test (no deterministic term in the residual ADF, N=2 variables). Used when
# statsmodels is unavailable so consumers can still compare the statistic.
_EG_CRITICAL_VALUES: dict[str, float] = {"1%": -3.90, "5%": -3.34, "10%": -3.04}

__all__ = [
    "ANNUAL",
    "autocorrelation",
    "beta",
    "cagr",
    "correlation",
    "drawdown",
    "ema",
    "engle_granger",
    "equity_curve",
    "ewma_volatility",
    "hurst_exponent",
    "log_returns",
    "max_drawdown",
    "ou_half_life",
    "realized_volatility",
    "rolling_mean",
    "rolling_ols_beta",
    "rolling_std",
    "rolling_zscore",
    "sharpe",
    "simple_returns",
    "to_records",
    "transaction_costs",
]


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


def simple_returns(close: pd.Series) -> pd.Series:
    """P_t / P_{t-1} - 1. First observation is NaN."""
    return close / close.shift(1) - 1.0


def log_returns(close: pd.Series) -> pd.Series:
    """ln(P_t / P_{t-1}). First observation is NaN."""
    return np.log(close / close.shift(1))


# ---------------------------------------------------------------------------
# Rolling statistics (trailing, min_periods=window -> NaN during warm-up)
# ---------------------------------------------------------------------------


def rolling_mean(s: pd.Series, window: int) -> pd.Series:
    """Trailing mean; NaN until `window` observations are available."""
    return s.rolling(window, min_periods=window).mean()


def rolling_std(s: pd.Series, window: int) -> pd.Series:
    """Trailing sample std (ddof=1); NaN until `window` observations."""
    return s.rolling(window, min_periods=window).std(ddof=1)


def rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    """(s - trailing mean) / trailing std.

    Both moments come from windows ending at bar ``t`` inclusive, so the
    z-score at ``t`` is a function of bars ``<= t`` only -- no lookahead.
    NaN until `window` observations are available.
    """
    return (s - rolling_mean(s, window)) / rolling_std(s, window)


def ema(s: pd.Series, window: int) -> pd.Series:
    """Exponential moving average, span=window (adjust=False)."""
    return s.ewm(span=window, adjust=False).mean()


# ---------------------------------------------------------------------------
# Equity / performance
# ---------------------------------------------------------------------------


def drawdown(equity: pd.Series) -> pd.Series:
    """Relative drawdown: equity / running max - 1 (<= 0)."""
    return equity / equity.cummax() - 1.0


def max_drawdown(equity: pd.Series) -> float:
    """Deepest relative drawdown over the series (0.0 for monotonic equity)."""
    if equity.empty:
        return 0.0
    return float(drawdown(equity).min())


def sharpe(daily_returns: pd.Series) -> float | None:
    """Annualised Sharpe of daily returns: mean/std * sqrt(252), ddof=1.

    None when fewer than two observations or when the std is exactly zero
    (Sharpe is undefined for a constant return stream).
    """
    r = daily_returns.dropna()
    if len(r) < 2:
        return None
    sd = float(r.std(ddof=1))
    if not np.isfinite(sd) or sd == 0.0:
        return None
    return float(r.mean() / sd) * math.sqrt(ANNUAL)


def cagr(equity: pd.Series) -> float | None:
    """(last/first)^(252/n) - 1 where n = len(equity) - 1 trading days.

    None when there are zero return periods, the first equity value is not
    positive, or the final ratio is not positive (sign flips make the power
    undefined).
    """
    n = len(equity) - 1
    if n < 1 or equity.empty:
        return None
    first = float(equity.iloc[0])
    last = float(equity.iloc[-1])
    if not (first > 0.0):
        return None
    ratio = last / first
    if not (ratio > 0.0):
        return None
    return float(ratio ** (ANNUAL / n) - 1.0)


def equity_curve(daily_strategy_returns: pd.Series) -> pd.Series:
    """(1 + r).cumprod() normalised to start at exactly 1.0."""
    gross = (1.0 + daily_strategy_returns).cumprod()
    first = gross.iloc[0]
    return gross / first


def transaction_costs(weights: pd.DataFrame, cost_bps: float) -> pd.Series:
    """Per-bar cost of trading into `weights`.

    cost_t = cost_bps/1e4 * sum_i |w_{i,t} - w_{i,t-1}|

    The first row is treated as entry turnover against a flat book (0), per
    spec section 1: entering the initial position costs the full notional
    change, it is not free.
    """
    prev = weights.shift(1).fillna(0.0)
    turnover = (weights - prev).abs().sum(axis=1)
    return turnover * (cost_bps / 1e4)


# ---------------------------------------------------------------------------
# Cross-series statistics
# ---------------------------------------------------------------------------


def _aligned(y: pd.Series, x: pd.Series) -> pd.DataFrame:
    """Inner-join two series on their index and drop any row with a NaN."""
    return pd.concat([y.rename("y"), x.rename("x")], axis=1, join="inner").dropna()


def beta(y: pd.Series, x: pd.Series) -> float | None:
    """cov(x, y) / var(x) over the aligned overlap (ddof=1).

    None when the overlap has fewer than two observations or x has zero
    variance (beta is undefined).
    """
    df = _aligned(y, x)
    if len(df) < 2:
        return None
    vx = float(df["x"].var(ddof=1))
    if not np.isfinite(vx) or vx == 0.0:
        return None
    return float(df["x"].cov(df["y"]) / vx)


def correlation(y: pd.Series, x: pd.Series, window: int | None = None) -> pd.Series | float:
    """Pearson correlation of y and x.

    ``window=None`` -> scalar correlation over the full aligned overlap
    (None if fewer than two observations or either side is constant).
    ``window=int`` -> trailing rolling correlation, min_periods=window,
    NaN until `window` aligned observations are available.
    """
    df = _aligned(y, x)
    if window is None:
        if len(df) < 2:
            return None
        if df["y"].std(ddof=1) == 0.0 or df["x"].std(ddof=1) == 0.0:
            return None
        return float(df["y"].corr(df["x"]))
    if len(df) < 2:
        return df["y"].rolling(window, min_periods=window).corr(df["x"]) * np.nan
    return df["y"].rolling(window, min_periods=window).corr(df["x"])


def autocorrelation(s: pd.Series, lag: int = 1) -> float | None:
    """Pearson correlation of the demeaned series with itself `lag` bars back.

    Compares s[t] with s[t-lag] over the overlapping observations. None when
    the overlap is shorter than two observations or either slice is constant.
    """
    v = s.dropna()
    if len(v) <= lag or lag < 1:
        return None
    a = v.iloc[lag:].to_numpy(dtype=float)
    b = v.iloc[:-lag].to_numpy(dtype=float)
    a = a - a.mean()
    b = b - b.mean()
    if a.std() == 0.0 or b.std() == 0.0:
        return None
    denom = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    if denom == 0.0:
        return None
    return float((a * b).sum()) / denom


def rolling_ols_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    """Trailing OLS slope of y on x (with intercept), min_periods=window.

    beta_t = cov_t(x, y) / var_t(x) over the trailing `window` bars ending
    at t inclusive -- a function of data <= t only. NaN during warm-up and
    wherever the trailing x-variance is zero. Indexed by the aligned
    (inner-join, NaN-dropped) overlap of the two inputs.
    """
    df = _aligned(y, x)
    cov = df["y"].rolling(window, min_periods=window).cov(df["x"])
    var = df["x"].rolling(window, min_periods=window).var()
    with np.errstate(divide="ignore", invalid="ignore"):
        out = cov / var
    out = out.replace([np.inf, -np.inf], np.nan)
    return out


# ---------------------------------------------------------------------------
# Time-series tests
# ---------------------------------------------------------------------------


def _ols(y: np.ndarray, x_cols: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Plain OLS. Returns (coef, resid, coef_std_err) via the classic normal
    equations and the residual-variance-scaled (X'X)^-1 diagonal."""
    n, k = x_cols.shape
    xtx = x_cols.T @ x_cols
    xtx_inv = np.linalg.pinv(xtx)
    coef = xtx_inv @ (x_cols.T @ y)
    resid = y - x_cols @ coef
    dof = n - k
    rss = float(resid @ resid)
    sigma2 = rss / dof if dof > 0 else np.nan
    se = np.sqrt(np.maximum(sigma2 * np.diag(xtx_inv), 0.0)) if dof > 0 else np.full(k, np.nan)
    return coef, resid, se


def _student_t_two_sided_p(t: float, df: int) -> float:
    """Two-sided p-value of Student's t via the regularised incomplete beta
    (continued-fraction form, Numerical Recipes). Pure stdlib math -- no
    scipy dependency."""
    if not np.isfinite(t) or df < 1:
        return float("nan")
    x = df / (df + t * t)
    return _betainc(df / 2.0, 0.5, x)


def _betacf(a: float, b: float, x: float, itmax: int = 200, eps: float = 3e-12) -> float:
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def engle_granger(y: pd.Series, x: pd.Series) -> dict:
    """Engle-Granger two-step cointegration test.

    Step 1: OLS of y on [1, x]. Step 2: ADF regression of the residuals
    with no deterministic term and no lagged differences:
    e_t = gamma * e_{t-1} + u_t, statistic = t-stat of gamma.

    Returns {'statistic', 'p_value' (statsmodels adfuller when importable,
    else None), 'critical_values', 'n_obs', 'window_note'}.
    """
    df = _aligned(y, x)
    n_obs = int(len(df))
    note = (
        "engle-granger two-step over the full aligned overlap: "
        "OLS y ~ [1, x], ADF(regression='n', maxlag=0) on residuals"
    )
    out: dict[str, Any] = {
        "statistic": None,
        "p_value": None,
        "critical_values": dict(_EG_CRITICAL_VALUES),
        "n_obs": n_obs,
        "window_note": note,
    }
    if n_obs < 3:
        return out
    yv = df["y"].to_numpy(dtype=float)
    xmat = np.column_stack([np.ones(n_obs), df["x"].to_numpy(dtype=float)])
    _, resid, _ = _ols(yv, xmat)
    # ADF with no constant and no lagged differences on the residuals.
    d_res = np.diff(resid)
    lag_res = resid[:-1]
    n_adf = d_res.size
    if n_adf < 2:
        return out
    coef, _, se = _ols(d_res, lag_res.reshape(-1, 1))
    gamma = float(coef[0])
    gamma_se = float(se[0])
    if not np.isfinite(gamma_se) or gamma_se == 0.0:
        return out
    stat = gamma / gamma_se
    out["statistic"] = float(stat)
    try:  # optional dependency; spec allows None p-value without it
        from statsmodels.tsa.stattools import adfuller  # noqa: PLC0415

        _, pvalue, _, _, _ = adfuller(resid, maxlag=0, regression="n", autolag=None)
        out["p_value"] = float(pvalue)
    except Exception:
        out["p_value"] = None
    return out


def ou_half_life(spread: pd.Series) -> dict:
    """Ornstein-Uhlenbeck half-life of a spread.

    Fits dS_t = alpha + lambda * S_{t-1} + eps_t by OLS (slope standard
    error computed here, not via a stats package). The spread is only
    called measurably mean-reverting when lambda < 0 AND the two-sided
    p-value of the slope is < 0.05; then half_life = -ln(2)/lambda.

    Returns {'lambda', 'half_life', 'mean_reverting', 'n_obs'}.
    """
    s = spread.dropna()
    n_obs = int(len(s) - 1)
    out: dict[str, Any] = {
        "lambda": None,
        "half_life": None,
        "mean_reverting": False,
        "n_obs": n_obs,
    }
    if n_obs < 3:
        return out
    s_prev = s.iloc[:-1].to_numpy(dtype=float)
    ds = s.iloc[1:].to_numpy(dtype=float) - s_prev
    xmat = np.column_stack([np.ones(n_obs), s_prev])
    coef, _, se = _ols(ds, xmat)
    lam = float(coef[1])
    lam_se = float(se[1])
    out["lambda"] = lam
    if not np.isfinite(lam_se) or lam_se == 0.0:
        return out
    t_stat = lam / lam_se
    p = _student_t_two_sided_p(t_stat, n_obs - 2)
    if not np.isfinite(p):
        return out
    mean_reverting = bool(lam < 0.0 and p < 0.05)
    out["mean_reverting"] = mean_reverting
    if mean_reverting:
        out["half_life"] = -math.log(2.0) / lam
    return out


def hurst_exponent(s: pd.Series, max_lag: int = 100) -> float | None:
    """Rescaled-range (R/S) Hurst exponent.

    For each lag L in [2, min(max_lag, n//2)] the series is split into
    consecutive non-overlapping chunks of length L; each chunk contributes
    R/S = range of the demeaned cumulative sum / sample std. The exponent is
    the slope of log(E[R/S]) against log(L). None when n < 60.
    """
    v = s.dropna().to_numpy(dtype=float)
    n = v.size
    if n < 60:
        return None
    max_l = min(int(max_lag), n // 2)
    if max_l < 2:
        return None
    log_rs: list[float] = []
    log_l: list[float] = []
    for lag in range(2, max_l + 1):
        m = n // lag
        chunks = v[: m * lag].reshape(m, lag)
        z = np.cumsum(chunks - chunks.mean(axis=1, keepdims=True), axis=1)
        r = np.ptp(z, axis=1)
        sd = chunks.std(axis=1, ddof=1)
        ok = sd > 0
        if not ok.any():
            continue
        rs = float(np.mean(r[ok] / sd[ok]))
        if rs > 0:
            log_rs.append(math.log(rs))
            log_l.append(math.log(lag))
    if len(log_rs) < 2:
        return None
    a = np.polyfit(np.asarray(log_l), np.asarray(log_rs), 1)
    h = float(a[0])
    if not np.isfinite(h):
        return None
    return h


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _iso_date(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return _iso_date(value)
    if hasattr(value, "isoformat"):
        return _iso_date(value)
    return value


def to_records(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    """DataFrame rows -> JSON-safe dicts: {'date': iso, <col>: value}.

    Only the listed columns are emitted. NaN/NaT become None (so a missing
    metric serialises as explicit null, never a fabricated value), index
    entries become ISO date strings, numpy scalars become plain Python
    types.
    """
    records: list[dict] = []
    for idx, row in df.iterrows():
        rec: dict[str, Any] = {"date": _iso_date(idx)}
        for col in cols:
            rec[col] = _json_safe(row[col])
        records.append(rec)
    return records