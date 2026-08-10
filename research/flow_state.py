"""
Flow-state feature engine for forced-flow / liquidity-shock detection.

Pure functions, no I/O, no network. Every function here takes data already
in memory (a tidy per-symbol OHLCV ``pd.DataFrame`` or an aligned
``pd.Series``) and returns a derived Series/DataFrame/scalar. Callers that
need to read parquet, CSV, or any other file live in
``research/flow_state_panel.py`` (or ``tools/``), never here — matches the
separation ``research/microstructure.py`` and ``research/labels.py`` use.

Motivation (see the accompanying plan doc): approximate Carlin-Lobo-
Viswanathan-style permanent/temporary price-impact decomposition using only
daily OHLCV + FINRA short-interest proxies -- there is no trades/quotes/L2
data anywhere in this repo. Every "impact", "spread", or "depth" estimate
below is a *descriptive proxy*, not a causal identification; that caveat is
repeated on the functions where it matters most.

Causality / no-lookahead contract
----------------------------------
All rolling windows in this module are trailing-only: a value computed "as
of" row ``t`` uses rows ``<= t`` and nothing from ``t+1`` onward. There are
no centered windows and no negative ``shift()`` calls anywhere in this file.
The two explicit exceptions, both documented at the call site, are:

* ``barrier_density`` — a single as-of-last-row snapshot computed from all
  bars supplied to it (not a per-row rolling series); every bar it consumes
  is, by construction, already known as of "now".
* ``extract_events`` — its ``resolution_state``/``resolution_date`` columns
  are intentionally forward-looking labels (they describe how an episode
  resolved), not features.

Inputs to per-symbol functions are tidy OHLCV ``pd.DataFrame`` objects with
columns ``open, high, low, close, volume`` and an ascending, duplicate-free
``DatetimeIndex`` — the same convention ``research/labels.py`` and
``research/regimes.py`` validate against, and the on-disk layout of
``data/1d_wide/*.parquet`` (checked directly: columns
``['open', 'high', 'low', 'close', 'volume']``, ascending unique
``DatetimeIndex``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

import numpy as np
import pandas as pd

REQUIRED_OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

ALL_STATES: tuple[str, ...] = (
    "NORMAL", "PRESSURE", "SHOCK", "TEST", "CASCADE", "ABSORB", "EXHAUSTION", "FADE",
)


# ---------------------------------------------------------------------------
# Validation helpers (mirrors research/labels.py / research/regimes.py style)
# ---------------------------------------------------------------------------

def _validate_ascending_unique_index(index: pd.Index, *, label: str) -> None:
    if not index.is_monotonic_increasing:
        raise ValueError(f"{label} index must be sorted in ascending order")
    if index.has_duplicates:
        raise ValueError(f"{label} index must not contain duplicate timestamps")


def _validate_ohlcv(bars: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_OHLCV_COLUMNS if c not in bars.columns]
    if missing:
        raise KeyError(f"missing OHLCV columns: {missing}")
    _validate_ascending_unique_index(bars.index, label="bars")


def _validate_series(series: pd.Series, *, label: str = "series") -> None:
    _validate_ascending_unique_index(series.index, label=label)


# ---------------------------------------------------------------------------
# 1. Signed volume proxy
# ---------------------------------------------------------------------------

def signed_volume_proxy(bars: pd.DataFrame) -> pd.Series:
    """Close-location-value x volume: ``((2*close-high-low)/(high-low)) * volume``.

    Zero-range bars (``high == low``) contribute 0, not NaN/inf.
    """
    _validate_ohlcv(bars)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    volume = bars["volume"].astype(float)

    range_ = high - low
    clv = pd.Series(0.0, index=bars.index)
    safe = range_ > 0
    clv.loc[safe] = (2.0 * close.loc[safe] - high.loc[safe] - low.loc[safe]) / range_.loc[safe]
    return (clv * volume).rename("signed_volume_proxy")


# ---------------------------------------------------------------------------
# Shared robust z-score helper (used by flow_z, short_pressure_z, amihud_shock)
# ---------------------------------------------------------------------------

def _mad(window_values: np.ndarray) -> float:
    med = np.median(window_values)
    return float(np.median(np.abs(window_values - med)))


def _robust_z(series: pd.Series, window: int) -> pd.Series:
    """Trailing robust z-score: ``(x - rolling_median) / (1.4826 * rolling_MAD)``.

    Both the median and MAD are recomputed for the same trailing window
    ending at each row (no lookahead). NaN during warm-up (< ``window``
    observations) and wherever the scaled MAD is exactly 0.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    values = pd.to_numeric(series, errors="coerce")
    med = values.rolling(window, min_periods=window).median()
    mad = values.rolling(window, min_periods=window).apply(_mad, raw=True)
    scaled_mad = mad * 1.4826
    z = (values - med) / scaled_mad.replace(0.0, np.nan)
    return z


# ---------------------------------------------------------------------------
# 2. flow_z
# ---------------------------------------------------------------------------

def flow_z(flow: pd.Series, window: int) -> pd.Series:
    """Robust median/MAD z-score of a signed-flow series. See ``_robust_z``."""
    _validate_series(flow, label="flow")
    return _robust_z(flow, window).rename("flow_z")


# ---------------------------------------------------------------------------
# 3. hourly_seasonal_adjust
# ---------------------------------------------------------------------------

def hourly_seasonal_adjust(series: pd.Series) -> pd.Series:
    """Subtract the trailing (expanding) median-by-hour-of-day from ``series``.

    Supplementary / optional: only meaningful on the 59-symbol hourly subset
    (``data/1h/``); never required by any gating logic. The baseline for hour
    bucket ``h`` at row ``t`` is the expanding median of all prior (and the
    current) observations in that same hour bucket -- causal, never uses a
    future observation.
    """
    _validate_series(series, label="series")
    hours = pd.Series(series.index.hour, index=series.index, name="hour")
    values = pd.to_numeric(series, errors="coerce")
    baseline = values.groupby(hours).transform(lambda s: s.expanding(min_periods=1).median())
    return (values - baseline).rename("hourly_seasonal_adjust")


# ---------------------------------------------------------------------------
# 4. flow_persistence
# ---------------------------------------------------------------------------

def flow_persistence(
    flow_z_series: pd.Series,
    threshold: float,
    windows: tuple[int, ...] = (3, 5, 10),
) -> pd.DataFrame:
    """Trailing same-sign shock-day counts, one column per window.

    Column ``persistence_{w}d`` at row ``t`` counts rows in the trailing
    ``w``-row window ending at ``t`` (inclusive) whose sign matches
    ``sign(flow_z[t])`` and whose magnitude exceeds ``threshold``. NaN until
    the full window is available.
    """
    _validate_series(flow_z_series, label="flow_z")
    if threshold < 0:
        raise ValueError("threshold must be non-negative")
    if not windows or any(w < 1 for w in windows):
        raise ValueError("windows must be non-empty and positive")

    values = pd.to_numeric(flow_z_series, errors="coerce")

    def _count(window_values: np.ndarray, threshold: float = threshold) -> float:
        current_sign = np.sign(window_values[-1])
        matches = (np.sign(window_values) == current_sign) & (np.abs(window_values) > threshold)
        return float(np.sum(matches))

    result = pd.DataFrame(index=flow_z_series.index)
    for w in windows:
        result[f"persistence_{w}d"] = values.rolling(w, min_periods=w).apply(_count, raw=True)
    return result


# ---------------------------------------------------------------------------
# 5. short_pressure_z
# ---------------------------------------------------------------------------

def short_pressure_z(short_ratio: pd.Series, window: int) -> pd.Series:
    """Robust z-score of a FINRA short-ratio series. Reuses ``_robust_z``."""
    _validate_series(short_ratio, label="short_ratio")
    return _robust_z(short_ratio, window).rename("short_pressure_z")


# ---------------------------------------------------------------------------
# 6/7. Amihud illiquidity + shock
# ---------------------------------------------------------------------------

def amihud_illiquidity(bars: pd.DataFrame, window: int = 21) -> pd.Series:
    """Rolling mean of ``abs(daily_return) / dollar_volume``.

    ``dollar_volume = close * volume``; guarded against divide-by-zero (a
    zero dollar-volume row is treated as missing for the ratio, not inf).
    """
    _validate_ohlcv(bars)
    close = bars["close"].astype(float)
    volume = bars["volume"].astype(float)
    returns = close.pct_change()
    dollar_volume = (close * volume).replace(0.0, np.nan)
    ratio = returns.abs() / dollar_volume
    return ratio.rolling(window, min_periods=window).mean().rename("amihud_illiquidity")


def amihud_shock(amihud: pd.Series, window: int) -> pd.Series:
    """Robust z (via ``_robust_z``) of ``diff(log(amihud))`` -- liquidity fragility."""
    _validate_series(amihud, label="amihud")
    log_amihud = np.log(amihud.where(amihud > 0))
    return _robust_z(log_amihud.diff(), window).rename("amihud_shock")


# ---------------------------------------------------------------------------
# 8. Corwin-Schultz spread
# ---------------------------------------------------------------------------

def corwin_schultz_spread(bars: pd.DataFrame, smooth_window: int = 5) -> pd.Series:
    """Corwin & Schultz (2012) 2-day high-low bid-ask spread estimator.

    Source: Corwin, S. A., & Schultz, P. (2012), "A Simple Way to Estimate
    Bid-Ask Spreads from Daily High and Low Prices", Journal of Finance
    67(2). For adjacent days ``t-1, t``::

        beta  = ln(H_t/L_t)^2 + ln(H_{t-1}/L_{t-1})^2
        gamma = ln(max(H_t,H_{t-1}) / min(L_t,L_{t-1}))^2
        k     = 3 - 2*sqrt(2)
        alpha = (sqrt(2*beta) - sqrt(beta)) / k - sqrt(gamma / k)
        S     = 2*(exp(alpha) - 1) / (1 + exp(alpha))

    A negative ``alpha`` is floored at 0 before exponentiating (the
    published convention), which also floors ``S`` at 0. A short rolling
    mean (``smooth_window``) is then applied on top of the raw daily
    estimate as a separate smoothing step.
    """
    _validate_ohlcv(bars)
    if smooth_window < 1:
        raise ValueError("smooth_window must be positive")
    high = bars["high"].astype(float).where(lambda s: s > 0)
    low = bars["low"].astype(float).where(lambda s: s > 0)

    log_hl = np.log(high / low)
    beta = log_hl.pow(2) + log_hl.shift(1).pow(2)
    two_day_high = high.rolling(2, min_periods=2).max()
    two_day_low = low.rolling(2, min_periods=2).min()
    gamma = np.log(two_day_high / two_day_low).pow(2)

    k = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    alpha = alpha.clip(lower=0.0)
    spread = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    spread = spread.clip(lower=0.0)
    return spread.rolling(smooth_window, min_periods=smooth_window).mean().rename("corwin_schultz_spread")


# ---------------------------------------------------------------------------
# 9. impact_beta
# ---------------------------------------------------------------------------

def impact_beta(returns: pd.Series, signed_flow_z: pd.Series, window: int = 63) -> pd.Series:
    """Rolling OLS slope of ``returns`` on ``signed_flow_z`` via cov/var.

    Descriptive state feature, not a causal impact estimate -- there is no
    identification strategy here, just a trailing bivariate slope.
    """
    _validate_series(returns, label="returns")
    _validate_series(signed_flow_z, label="signed_flow_z")
    if not returns.index.equals(signed_flow_z.index):
        raise ValueError("returns and signed_flow_z must share the same index")
    if window < 2:
        raise ValueError("window must be >= 2")

    x = pd.to_numeric(signed_flow_z, errors="coerce")
    y = pd.to_numeric(returns, errors="coerce")
    mean_x = x.rolling(window, min_periods=window).mean()
    mean_y = y.rolling(window, min_periods=window).mean()
    cov = (x * y).rolling(window, min_periods=window).mean() - mean_x * mean_y
    var_x = (x * x).rolling(window, min_periods=window).mean() - mean_x * mean_x
    beta = cov / var_x.replace(0.0, np.nan)
    return beta.rename("impact_beta")


# ---------------------------------------------------------------------------
# 10. impact_response_curve
# ---------------------------------------------------------------------------

def impact_response_curve(returns: pd.Series, shock_mask: pd.Series, max_lag: int = 10) -> pd.DataFrame:
    """Event-study forward cumulative-return curve across all ``shock_mask`` events.

    For each ``True`` in ``shock_mask`` at position ``t0``, computes the
    forward cumulative return to ``t0 + lag`` for ``lag in 1..max_lag`` and
    aggregates across all events with a normal-approximation 95% CI. Meant
    to be called once per artifact build across an event set, not per-row.
    Returns columns ``lag, mean_cum_ret, ci_lo, ci_hi, n``.
    """
    _validate_series(returns, label="returns")
    _validate_series(shock_mask, label="shock_mask")
    if not returns.index.equals(shock_mask.index):
        raise ValueError("returns and shock_mask must share the same index")
    if max_lag < 1:
        raise ValueError("max_lag must be positive")

    log_ret = np.log1p(pd.to_numeric(returns, errors="coerce"))
    cum_log = log_ret.cumsum().to_numpy()
    event_positions = np.flatnonzero(shock_mask.fillna(False).to_numpy())
    n_obs = len(returns)

    rows: list[dict] = []
    for lag in range(1, max_lag + 1):
        samples = []
        for pos in event_positions:
            target = pos + lag
            if target < n_obs and np.isfinite(cum_log[pos]) and np.isfinite(cum_log[target]):
                samples.append(np.exp(cum_log[target] - cum_log[pos]) - 1.0)
        arr = np.asarray(samples, dtype=float)
        n = int(arr.size)
        if n > 0:
            mean = float(arr.mean())
            if n > 1:
                se = float(arr.std(ddof=1) / np.sqrt(n))
                ci_lo, ci_hi = mean - 1.96 * se, mean + 1.96 * se
            else:
                ci_lo = ci_hi = np.nan
        else:
            mean = ci_lo = ci_hi = np.nan
        rows.append({"lag": lag, "mean_cum_ret": mean, "ci_lo": ci_lo, "ci_hi": ci_hi, "n": n})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# FlowStateConfig -- every threshold/window used below is a named field here
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FlowStateConfig:
    """Every numeric threshold and window used by this module, in one place.

    Grouped so Phase 2+ can vary thresholds (grid search, sensitivity
    analysis, preregistration) without touching any function body.
    """

    # -- robust z / rolling windows --------------------------------------
    flow_z_window: int = 20
    short_pressure_window: int = 20
    amihud_window: int = 21
    amihud_shock_window: int = 20
    corwin_schultz_smooth_window: int = 5
    impact_beta_window: int = 63
    cross_asset_window: int = 63

    # -- flow persistence ---------------------------------------------------
    flow_persistence_threshold: float = 1.5
    flow_persistence_windows: tuple[int, ...] = (3, 5, 10)

    # -- barrier density kernel -------------------------------------------
    barrier_atr_window: int = 14
    barrier_swing_lookback: int = 5
    barrier_bandwidth_atr_mult: float = 0.5
    barrier_weight_swing: float = 1.0
    barrier_weight_volume: float = 1.0
    barrier_weight_round: float = 0.5
    barrier_weight_anchor: float = 0.75
    barrier_anchor_lookback_n: int = 5
    barrier_volume_price_points: int = 5

    # -- periodic barrier recompute cadence (used by flow_state_panel) -----
    # barrier_density is an O(n) snapshot (swing-pivot scan + volume-at-price
    # spread); recomputing it at every row for 557 symbols x ~2500 sessions
    # is not tractable for a nightly batch build. flow_state_panel instead
    # recomputes it every barrier_recompute_every_n_days trading days (using
    # only bars available up to that point -- still trailing-only) and
    # forward-fills the result to the rows in between; the barrier field
    # genuinely does not move much day to day, so this is a bounded-cost
    # approximation, not a shortcut. Each recompute additionally bounds its
    # input to the trailing barrier_history_lookback_bars bars rather than
    # full symbol history, since barrier_density's linear time-decay already
    # makes bars past that window contribute negligible mass.
    barrier_recompute_every_n_days: int = 10
    barrier_history_lookback_bars: int = 504

    # -- deterministic-classifier thresholds -------------------------------
    shock_flow_z: float = 3.0
    shock_amihud_z: float = 2.0
    pressure_persistence_min: int = 3
    pressure_persistence_window: int = 5
    test_atr_mult: float = 0.5
    test_flow_z_min: float = 1.5
    cascade_air_pocket_min: float = 5.0
    absorb_volume_ratio_min: float = 1.5
    absorb_range_compression_max: float = 0.8
    exhaustion_lookback: int = 3
    exhaustion_amihud_z_min: float = 1.0
    fade_replenish_z: float = 0.5
    fade_lookback: int = 5

    # -- barrier-conditioned continuation sleeve (evidence-backed candidate) --
    # S_t = |Z_flow| * max(Z_impact, 0) * Persistence * exp(-d_barrier / tau)
    # Direction is sign(flow). This is the narrowed interaction the matched-
    # control work supports investigating; cascade/fade are intentionally
    # excluded from this score.
    impact_beta_z_window: int = 63
    continuation_barrier_tau: float = 0.5
    continuation_persistence_window: int = 5

    def __post_init__(self) -> None:
        windows = [
            self.flow_z_window, self.short_pressure_window, self.amihud_window,
            self.amihud_shock_window, self.corwin_schultz_smooth_window,
            self.impact_beta_window, self.cross_asset_window, self.barrier_atr_window,
            self.barrier_swing_lookback,
        ]
        if any(w < 2 for w in windows):
            raise ValueError("all rolling windows must be >= 2")
        if self.pressure_persistence_window not in self.flow_persistence_windows:
            raise ValueError(
                "pressure_persistence_window must be one of flow_persistence_windows"
            )
        if self.barrier_bandwidth_atr_mult <= 0:
            raise ValueError("barrier_bandwidth_atr_mult must be positive")
        if self.shock_flow_z <= 0 or self.test_flow_z_min <= 0 or self.pressure_persistence_min < 1:
            raise ValueError("classifier thresholds must be positive")
        if self.test_flow_z_min >= self.shock_flow_z:
            raise ValueError("test_flow_z_min must be strictly below shock_flow_z")
        if self.barrier_recompute_every_n_days < 1:
            raise ValueError("barrier_recompute_every_n_days must be positive")
        if self.barrier_history_lookback_bars < self.barrier_atr_window:
            raise ValueError("barrier_history_lookback_bars must be >= barrier_atr_window")
        if self.impact_beta_z_window < 2:
            raise ValueError("impact_beta_z_window must be >= 2")
        if self.continuation_barrier_tau <= 0:
            raise ValueError("continuation_barrier_tau must be positive")
        if self.continuation_persistence_window not in self.flow_persistence_windows:
            raise ValueError(
                "continuation_persistence_window must be one of flow_persistence_windows"
            )


# ---------------------------------------------------------------------------
# 11. barrier_density
# ---------------------------------------------------------------------------

def _swing_pivots(bars: pd.DataFrame, lookback: int) -> tuple[pd.Series, pd.Series]:
    """Trailing rolling-window argmax/argmin pivot detector.

    Bar ``i`` is a swing high if its ``high`` equals the maximum ``high``
    over the trailing ``lookback``-bar window ending at ``i`` (a rolling
    argmax); a swing low is the symmetric rolling argmin over ``low``. This
    intentionally stays trailing-only (no centered window / no lookahead),
    at the cost of also tagging every bar of a monotonic run -- acceptable
    for a density-weighting heuristic, not a precise "swing point" detector.
    """
    if lookback < 1:
        raise ValueError("lookback must be positive")
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    rolling_high_max = high.rolling(lookback, min_periods=lookback).max()
    rolling_low_min = low.rolling(lookback, min_periods=lookback).min()
    is_swing_high = rolling_high_max.notna() & high.ge(rolling_high_max)
    is_swing_low = rolling_low_min.notna() & low.le(rolling_low_min)
    return is_swing_high.rename("swing_high"), is_swing_low.rename("swing_low")


def _round_number_increment(price: float) -> float:
    """Round-number grid step scaled by price magnitude (repo convention)."""
    if price < 20.0:
        return 1.0
    if price < 100.0:
        return 5.0
    return 10.0


def _true_range(bars: pd.DataFrame) -> pd.Series:
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    return pd.concat(
        [(high - low).abs(), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1,
    ).max(axis=1)


def _trailing_atr(bars: pd.DataFrame, window: int) -> pd.Series:
    """Trailing mean true range, causal (``min_periods=1`` so it is never NaN
    once at least one bar is available). Shared by ``barrier_density`` (for
    kernel bandwidth) and ``flow_state_panel`` (for per-row barrier-distance
    scaling), so both use the same ATR definition.
    """
    return _true_range(bars).rolling(window, min_periods=1).mean()


def barrier_density(bars: pd.DataFrame, grid: np.ndarray, cfg: FlowStateConfig) -> pd.Series:
    """Gaussian-kernel price-level density AS OF THE LAST ROW of ``bars``.

    This is a current-state snapshot (meant to be called once per symbol
    per artifact build, given all bars up to "now"), not a rolling per-row
    series. Mass is added from four sources, each weighted by a
    ``cfg.barrier_weight_*`` constant:

    (a) rolling swing highs/lows (``_swing_pivots``);
    (b) volume-at-price nodes -- each bar's volume is spread uniformly over
        ``cfg.barrier_volume_price_points`` levels across its
        ``[low, high]`` range, linearly time-decayed so older bars
        contribute less;
    (c) round numbers, spaced by ``_round_number_increment(last_close)``;
    (d) anchored typical-price means ``(high+low+close)/3`` (the repo's
        documented VWAP-proxy convention, ``tools/qlib_ingest.py``) from the
        last ``cfg.barrier_anchor_lookback_n`` swing anchors.

    Bandwidth is ``cfg.barrier_bandwidth_atr_mult * ATR`` (ATR from a
    trailing ``cfg.barrier_atr_window``-bar mean true range, evaluated at
    the last row).
    """
    _validate_ohlcv(bars)
    if len(bars) == 0:
        raise ValueError("bars must be non-empty")
    grid_arr = np.asarray(grid, dtype=float)
    if grid_arr.ndim != 1 or grid_arr.size < 2:
        raise ValueError("grid must be a 1-D array with at least two price levels")

    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    volume = bars["volume"].astype(float)

    atr = _trailing_atr(bars, cfg.barrier_atr_window).iloc[-1]
    last_close = float(close.iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        atr = max(last_close * 0.01, 1e-6)
    bandwidth = max(cfg.barrier_bandwidth_atr_mult * atr, 1e-6)

    density = np.zeros_like(grid_arr, dtype=float)
    norm = 1.0 / (bandwidth * np.sqrt(2.0 * np.pi))

    def _add(center: float, weight: float) -> None:
        if weight <= 0 or not np.isfinite(center):
            return
        kernel = np.exp(-0.5 * np.square((grid_arr - center) / bandwidth)) * norm
        nonlocal density
        density = density + weight * kernel

    # (a) swing pivots
    is_high, is_low = _swing_pivots(bars, cfg.barrier_swing_lookback)
    for price in high.loc[is_high]:
        _add(float(price), cfg.barrier_weight_swing)
    for price in low.loc[is_low]:
        _add(float(price), cfg.barrier_weight_swing)

    # (b) volume-at-price, linear time-decay (oldest bar -> 0 weight, newest -> 1)
    n = len(bars)
    age = np.arange(n - 1, -1, -1)
    decay = 1.0 - age / max(n - 1, 1) if n > 1 else np.ones(1)
    n_points = max(int(cfg.barrier_volume_price_points), 1)
    high_vals, low_vals, vol_vals = high.to_numpy(), low.to_numpy(), volume.to_numpy()
    for i in range(n):
        bar_high, bar_low, bar_vol = high_vals[i], low_vals[i], vol_vals[i]
        if not (np.isfinite(bar_high) and np.isfinite(bar_low) and bar_vol > 0) or bar_high < bar_low:
            continue
        bar_weight = cfg.barrier_weight_volume * float(decay[i]) * float(bar_vol)
        if bar_high == bar_low or n_points == 1:
            _add(float(bar_high), bar_weight)
            continue
        per_point = bar_weight / n_points
        for level in np.linspace(bar_low, bar_high, n_points):
            _add(float(level), per_point)

    # (c) round numbers
    increment = _round_number_increment(last_close)
    lo, hi = float(grid_arr.min()), float(grid_arr.max())
    level = np.floor(lo / increment) * increment
    while level <= hi + increment:
        if lo <= level <= hi:
            _add(level, cfg.barrier_weight_round)
        level += increment

    # (d) anchored typical-price means from the last N swing anchors
    typical_price = (high + low + close) / 3.0
    anchor_mask = is_high | is_low
    anchors = typical_price.loc[anchor_mask].tail(cfg.barrier_anchor_lookback_n)
    for price in anchors:
        _add(float(price), cfg.barrier_weight_anchor)

    return pd.Series(density, index=pd.Index(grid_arr, name="price"), name="barrier_density")


# ---------------------------------------------------------------------------
# 12. air_pocket_score
# ---------------------------------------------------------------------------

def air_pocket_score(density: pd.Series, p_from: float, p_to: float, eps: float = 1e-6) -> float:
    """Discretized ``sum(grid_spacing / (density_at_p + eps))`` over ``[p_from, p_to]``."""
    if density.empty:
        raise ValueError("density must be non-empty")
    grid = density.index.to_numpy(dtype=float)
    lo, hi = sorted((float(p_from), float(p_to)))
    mask = (grid >= lo) & (grid <= hi)
    if not mask.any():
        return 0.0
    sub_grid = grid[mask]
    sub_density = density.to_numpy(dtype=float)[mask]
    if sub_grid.size >= 2:
        spacing = float(np.median(np.diff(sub_grid)))
    elif grid.size >= 2:
        spacing = float(np.median(np.diff(grid)))
    else:
        spacing = 1.0
    return float(np.sum(spacing / (sub_density + eps)))


# ---------------------------------------------------------------------------
# 13. nearest_nodes
# ---------------------------------------------------------------------------

def nearest_nodes(density: pd.Series, price: float) -> dict:
    """Nearest local-maxima nodes in ``density`` strictly below and above ``price``."""
    if density.empty:
        raise ValueError("density must be non-empty")
    ordered = density.sort_index()
    grid = ordered.index.to_numpy(dtype=float)
    values = ordered.to_numpy(dtype=float)
    n = len(grid)

    is_peak = np.ones(n, dtype=bool)
    if n > 1:
        left_ok = np.empty(n, dtype=bool)
        right_ok = np.empty(n, dtype=bool)
        left_ok[0], left_ok[1:] = True, values[1:] >= values[:-1]
        right_ok[-1], right_ok[:-1] = True, values[:-1] >= values[1:]
        is_peak = left_ok & right_ok

    peak_prices = grid[is_peak]
    peak_values = values[is_peak]

    result: dict = {
        "support_price": None, "support_mass": None,
        "resistance_price": None, "resistance_mass": None,
    }
    below = peak_prices < price
    above = peak_prices > price
    if below.any():
        idx = int(np.argmax(peak_prices[below]))
        result["support_price"] = float(peak_prices[below][idx])
        result["support_mass"] = float(peak_values[below][idx])
    if above.any():
        idx = int(np.argmin(peak_prices[above]))
        result["resistance_price"] = float(peak_prices[above][idx])
        result["resistance_mass"] = float(peak_values[above][idx])
    return result


# ---------------------------------------------------------------------------
# 14. cross_asset_residuals
# ---------------------------------------------------------------------------

def cross_asset_residuals(sym_rets: pd.Series, factor_rets: pd.DataFrame, window: int = 63) -> pd.Series:
    """Rolling, causal OLS residual of ``sym_rets`` on ``factor_rets`` columns.

    Refit at every step on the trailing ``window`` observations (a rolling
    ``numpy.linalg.lstsq`` per step); the residual at row ``t`` uses only
    the fit through ``t`` (inclusive), applied back to row ``t`` itself --
    no future data. ``research/sector_residual.py`` only exposes a fixed
    single-purpose ``sector_residual_momentum_20d`` transform, not a general
    multi-factor rolling-residual utility, so this is written fresh here
    rather than forcing a fit that doesn't exist.
    """
    _validate_series(sym_rets, label="sym_rets")
    _validate_ascending_unique_index(factor_rets.index, label="factor_rets")
    if not sym_rets.index.equals(factor_rets.index):
        raise ValueError("sym_rets and factor_rets must share the same index")
    n_factors = factor_rets.shape[1]
    if n_factors < 1:
        raise ValueError("factor_rets must have at least one factor column")
    if window < n_factors + 2:
        raise ValueError("window must exceed the number of factor columns")

    y = pd.to_numeric(sym_rets, errors="coerce").to_numpy(dtype=float)
    x = factor_rets.apply(lambda col: pd.to_numeric(col, errors="coerce")).to_numpy(dtype=float)
    n = len(y)
    residual = np.full(n, np.nan, dtype=float)

    for t in range(window - 1, n):
        y_win = y[t - window + 1: t + 1]
        x_win = x[t - window + 1: t + 1]
        valid = np.isfinite(y_win) & np.all(np.isfinite(x_win), axis=1)
        if valid.sum() < window:
            continue
        design = np.column_stack([np.ones(int(valid.sum())), x_win[valid]])
        coeffs, *_ = np.linalg.lstsq(design, y_win[valid], rcond=None)
        x_t = np.concatenate(([1.0], x[t]))
        residual[t] = y[t] - float(x_t @ coeffs)

    return pd.Series(residual, index=sym_rets.index, name="cross_asset_residual")


# ---------------------------------------------------------------------------
# 15. classify_states -- explicit, ordered, inspectable rule table
# ---------------------------------------------------------------------------

def _persistence_col(cfg: FlowStateConfig) -> str:
    return f"flow_persistence_{cfg.pressure_persistence_window}d"


def _required_state_columns(cfg: FlowStateConfig) -> tuple[str, ...]:
    return (
        "flow_z", "amihud_shock", _persistence_col(cfg), "dist_to_barrier_atr",
        "barrier_high_mass", "barrier_break_direction", "air_pocket_break",
        "volume_ratio", "range_compression", "signed_flow_sign",
    )


def _cond_shock(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    return (f["flow_z"].abs() > cfg.shock_flow_z) & (f["amihud_shock"] > cfg.shock_amihud_z)


def _cond_pressure(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    return f[_persistence_col(cfg)] >= cfg.pressure_persistence_min


def _near_high_mass_barrier(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    return (f["dist_to_barrier_atr"] <= cfg.test_atr_mult) & f["barrier_high_mass"].astype(bool)


def _cond_test(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    return _near_high_mass_barrier(f, cfg) & (f["flow_z"].abs() >= cfg.test_flow_z_min)


def _cond_cascade(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    broke = f["barrier_break_direction"] != 0
    air_pocket_ok = f["air_pocket_break"] > cfg.cascade_air_pocket_min
    continuing = f["signed_flow_sign"] == f["barrier_break_direction"]
    return broke & air_pocket_ok & continuing


def _cond_absorb(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    held = _near_high_mass_barrier(f, cfg) & (f["barrier_break_direction"] == 0)
    vol_surge = f["volume_ratio"] > cfg.absorb_volume_ratio_min
    compression = f["range_compression"] < cfg.absorb_range_compression_max
    return held & vol_surge & compression


def _cond_exhaustion(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    abs_flow = f["flow_z"].abs()
    decaying = pd.Series(True, index=f.index)
    for k in range(1, cfg.exhaustion_lookback + 1):
        decaying = decaying & (abs_flow < abs_flow.shift(k))
    decaying = decaying & abs_flow.notna()
    elevated = f["amihud_shock"] > cfg.exhaustion_amihud_z_min
    return decaying & elevated


def _cond_fade(f: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    # A prior EXHAUSTION *condition match* (not necessarily the final label
    # -- another rule can outrank EXHAUSTION at that historical row) within
    # the trailing fade_lookback rows, excluding the current row, followed
    # by Amihud renormalizing back toward baseline (small |amihud_shock|).
    raw_exhaustion = _cond_exhaustion(f, cfg).astype(bool).shift(1, fill_value=False).astype(int)
    exhaustion_recent = raw_exhaustion.rolling(cfg.fade_lookback, min_periods=1).max().astype(bool)
    renormalized = f["amihud_shock"].abs() < cfg.fade_replenish_z
    return exhaustion_recent & renormalized


# Explicit, ordered, inspectable rule table: (state name, condition fn).
# Evaluated top-to-bottom per row; first match wins; default is NORMAL.
STATE_RULES: tuple[tuple[str, Callable[[pd.DataFrame, FlowStateConfig], pd.Series]], ...] = (
    ("SHOCK", _cond_shock),
    ("PRESSURE", _cond_pressure),
    ("TEST", _cond_test),
    ("CASCADE", _cond_cascade),
    ("ABSORB", _cond_absorb),
    ("EXHAUSTION", _cond_exhaustion),
    ("FADE", _cond_fade),
)


def classify_states(features: pd.DataFrame, cfg: FlowStateConfig) -> pd.Series:
    """Deterministic state classifier over ``ALL_STATES``.

    Uses only ``features`` columns at row ``t`` and earlier (every condition
    function above is built from ``.rolling``/``.shift(k>=0)`` on ``features``
    columns, never a negative shift). Evaluates ``STATE_RULES`` top-to-bottom
    per row; the first matching rule wins; unmatched rows default to
    ``"NORMAL"``.

    Required ``features`` columns (see ``_required_state_columns``):
    ``flow_z``, ``amihud_shock``, ``flow_persistence_{cfg.pressure_persistence_window}d``,
    ``dist_to_barrier_atr``, ``barrier_high_mass``, ``barrier_break_direction``
    (in ``{-1, 0, 1}``), ``air_pocket_break``, ``volume_ratio``,
    ``range_compression``, ``signed_flow_sign`` (in ``{-1, 0, 1}``).
    """
    _validate_ascending_unique_index(features.index, label="features")
    required = _required_state_columns(cfg)
    missing = [c for c in required if c not in features.columns]
    if missing:
        raise KeyError(f"missing required classify_states columns: {missing}")

    result = pd.Series("NORMAL", index=features.index, dtype="object")
    assigned = pd.Series(False, index=features.index)
    for name, condition_fn in STATE_RULES:
        mask = condition_fn(features, cfg).fillna(False) & ~assigned
        result.loc[mask] = name
        assigned = assigned | mask
    return result.rename("state")


# ---------------------------------------------------------------------------
# 16. barrier_continuation_score
# ---------------------------------------------------------------------------

def barrier_continuation_score(
    flow_z_series: pd.Series,
    impact_beta_series: pd.Series,
    persistence_series: pd.Series,
    dist_to_barrier_atr: pd.Series,
    *,
    cfg: FlowStateConfig | None = None,
    impact_beta_z: pd.Series | None = None,
) -> pd.DataFrame:
    """Barrier-conditioned liquidity-momentum raw score (continuation sleeve).

    Implements the evidence-narrowed interaction candidate:

        S_t = |Z_flow_t| · max(Z_β_t, 0) · Persistence_t · exp(−d_t / τ)
        D_t = sign(Z_flow_t)

    where:
      * ``Z_flow`` is the robust flow z (``flow_z``),
      * ``Z_β`` is a trailing robust z of local impact beta (or a caller-
        supplied series), floored at 0 so only *elevated* impact contributes,
      * ``Persistence`` is the same-sign shock-day count in the configured
        window, scaled into ``[0, 1]`` by that window length,
      * ``d`` is distance to the nearest structural barrier in ATR units,
      * ``τ`` is ``cfg.continuation_barrier_tau`` (smooth proximity kernel).

    Returns a DataFrame with columns:
      ``continuation_score``, ``continuation_direction``, ``impact_beta_z``,
      ``barrier_proximity`` (= exp(−d/τ)).

    This is a *descriptive* ranking feature for research display and
    event tagging — not a live trading authorization and not a bottom/
    fade detector. Cascade/exhaustion/fade are deliberately out of scope.
    """
    cfg = cfg or FlowStateConfig()
    _validate_series(flow_z_series, label="flow_z")
    _validate_series(impact_beta_series, label="impact_beta")
    _validate_series(persistence_series, label="persistence")
    _validate_series(dist_to_barrier_atr, label="dist_to_barrier_atr")

    index = flow_z_series.index
    for name, series in (
        ("impact_beta", impact_beta_series),
        ("persistence", persistence_series),
        ("dist_to_barrier_atr", dist_to_barrier_atr),
    ):
        if not series.index.equals(index):
            raise ValueError(f"{name} must share flow_z's index")

    fz = pd.to_numeric(flow_z_series, errors="coerce")
    if impact_beta_z is None:
        z_beta = _robust_z(impact_beta_series, cfg.impact_beta_z_window)
    else:
        _validate_series(impact_beta_z, label="impact_beta_z")
        if not impact_beta_z.index.equals(index):
            raise ValueError("impact_beta_z must share flow_z's index")
        z_beta = pd.to_numeric(impact_beta_z, errors="coerce")

    z_beta_pos = z_beta.clip(lower=0.0)
    window = float(cfg.continuation_persistence_window)
    persistence_unit = (
        pd.to_numeric(persistence_series, errors="coerce").clip(lower=0.0) / window
    ).clip(upper=1.0)

    d = pd.to_numeric(dist_to_barrier_atr, errors="coerce")
    # Missing distance → treat as far from barrier (kernel → 0), not as NaN
    # that would zero out an otherwise readable row only after the product.
    proximity = np.exp(-d.fillna(10.0 * cfg.continuation_barrier_tau) / cfg.continuation_barrier_tau)

    score = fz.abs().fillna(0.0) * z_beta_pos.fillna(0.0) * persistence_unit.fillna(0.0) * proximity
    direction = np.sign(fz).fillna(0.0).astype(int)

    return pd.DataFrame(
        {
            "continuation_score": score.rename("continuation_score"),
            "continuation_direction": direction.rename("continuation_direction"),
            "impact_beta_z": z_beta.rename("impact_beta_z"),
            "barrier_proximity": proximity.rename("barrier_proximity"),
        },
        index=index,
    )


# ---------------------------------------------------------------------------
# 17. extract_events
# ---------------------------------------------------------------------------

def extract_events(states: pd.Series, features: pd.DataFrame, *, resolution_horizon: int = 20) -> pd.DataFrame:
    """One row per contiguous SHOCK or TEST episode.

    An episode is a maximal run of consecutive rows sharing the same state
    value (SHOCK or TEST). Columns: ``symbol`` (copied through if present in
    ``features``, otherwise the caller adds it), ``t0`` (episode start
    timestamp), ``direction`` (sign of ``flow_z`` at ``t0``, falling back to
    the sign of ``signed_volume_proxy`` at ``t0`` if ``flow_z`` is
    unavailable), every other feature column's value AT ``t0`` prefixed
    ``feat_`` (the frozen x-vector later phases train on),
    ``resolution_state`` (the state ``resolution_horizon`` bars after ``t0``,
    or the last available state if the horizon runs past the end of the
    series), and ``resolution_date``.
    """
    if not states.index.equals(features.index):
        raise ValueError("states and features must share the same index")
    _validate_ascending_unique_index(states.index, label="states")
    if resolution_horizon < 1:
        raise ValueError("resolution_horizon must be positive")

    target_states = {"SHOCK", "TEST"}
    state_values = states.to_numpy(dtype=object)
    n = len(state_values)

    rows: list[dict] = []
    i = 0
    while i < n:
        if state_values[i] in target_states:
            j = i
            while j + 1 < n and state_values[j + 1] == state_values[i]:
                j += 1
            direction = 0
            if "flow_z" in features.columns and pd.notna(features["flow_z"].iloc[i]):
                direction = int(np.sign(features["flow_z"].iloc[i]))
            elif "signed_volume_proxy" in features.columns and pd.notna(features["signed_volume_proxy"].iloc[i]):
                direction = int(np.sign(features["signed_volume_proxy"].iloc[i]))

            row: dict = {"t0": states.index[i], "direction": direction}
            if "symbol" in features.columns:
                row["symbol"] = features["symbol"].iloc[i]
            for col in features.columns:
                if col == "symbol":
                    continue
                row[f"feat_{col}"] = features[col].iloc[i]

            resolution_idx = min(i + resolution_horizon, n - 1)
            row["resolution_state"] = states.iloc[resolution_idx]
            row["resolution_date"] = states.index[resolution_idx]
            rows.append(row)
            i = j + 1
        else:
            i += 1

    return pd.DataFrame(rows)
