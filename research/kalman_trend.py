"""Kalman constant-velocity trend filter over log price.

Every moving average trades lag against smoothness, and picks that trade-off
once, for all regimes. A Kalman filter picks it continuously: model log price
as a level moving at a latent velocity, and weight each new observation by how
surprising it is relative to the noise the filter has been seeing. The result
tracks a real trend faster than an EMA of equal smoothness and absorbs a
single-bar shock better.

The tradeable output is the *velocity*, not the level. A real trend keeps the
filtered slope pinned above its own noise band; chop leaves it oscillating
around zero. Entry/exit hysteresis (enter high, exit low) stops the position
flickering on the boundary.

Model (standard linear-Gaussian state space, Kalman 1960):

    state   x_t = [level_t, velocity_t]'
    F       [[1, 1], [0, 1]]            constant velocity
    Q       q * I                       process noise on both states
    H       [1, 0]                      we observe the level only
    R       1                           observation variance

R is fixed at 1 because only the ratio q/R sets the gain -- a filter with
(q, R) and one with (cq, cR) produce identical estimates. Exposing both would
give the caller two knobs for one degree of freedom and invite tuning noise.

Three traps this module is written to avoid:

  1. **Horizons in bars, not time.** `noise_days` is a horizon in DAYS,
     converted to bars with the series' own spacing. A window written in bars
     silently means something different on every timeframe: "200" is eight
     days of hourly gold and eight months of daily Apple, and the same
     parameter file then behaves like two different strategies. Measure the
     bar, state the horizon in time -- see `bars_per_day` / `bars_for_days`.

  2. **Look-ahead at the fill.** The signal is read at bar i and the position
     is filled at bar i+1. `KalmanTrade` therefore stores fill indices, and
     the fill price a caller should use is bar i+1's OPEN, never bar i's
     close. Nothing here peeks at a bar the decision could not have seen.

  3. **A threshold in price units.** The slope is scaled by its own rolling
     standard deviation before it is compared to `entry_z`, so the threshold
     means the same thing on gold at $500 and gold at $4,000, and on a $3
     small cap as on a $600 index.

What this is NOT: a gate. The trade list is a descriptive, in-sample
reconstruction of what these thresholds would have flagged over the bars
supplied -- no costs, no slippage, no walk-forward, no multiple-testing
correction. This repo authorises trades only through its own gate modules
(`research/gates.py`); nothing here is one of them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

DEFAULT_Q = 1e-6
DEFAULT_ENTRY_Z = 1.0
DEFAULT_EXIT_Z = 0.0
DEFAULT_NOISE_DAYS = 20.0
#: Bars-per-day fallback when the index carries no usable spacing (one daily bar).
DEFAULT_BARS_PER_DAY = 1.0
#: Never let a day-denominated window collapse below this many bars -- a
#: 2-bar standard deviation is a coin flip, not a noise estimate.
MIN_NOISE_BARS = 3
_SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True)
class KalmanTrade:
    """One round trip. Indices are FILL bars, not signal bars.

    The signal that opened the position was read at `entry_i - 1` and the
    signal that closed it at `exit_i - 1`; both fills happen at the open of
    their own bar. `direction` is "long" or "short".
    """

    entry_i: int
    exit_i: int
    direction: str


@dataclass(frozen=True)
class KalmanTrendResult:
    """Filter output aligned 1:1 with the input bars.

    `level` and `slope` are the filtered state. `noise` is the rolling
    standard deviation of `slope` (NaN during warmup) and `score` is
    `slope / noise`, defined as 0.0 wherever the noise estimate is missing or
    zero -- a bar with no usable noise estimate must not be tradeable, and 0.0
    is below every non-negative `entry_z`.
    """

    level: np.ndarray
    slope: np.ndarray
    noise: np.ndarray
    score: np.ndarray
    trades: tuple[KalmanTrade, ...]
    #: True when the last trade was still open on the final bar and was closed
    #: by the harness rather than by an exit signal. Callers that report a
    #: track record must surface this -- a forced close is not a decision the
    #: strategy made.
    open_at_end: bool
    noise_bars: int
    bars_per_day: float
    velocity: np.ndarray | None = None
    velocity_zscore: np.ndarray | None = None
    velocity_noise: np.ndarray | None = None
    trend_state: np.ndarray | None = None
    persistence: np.ndarray | None = None
    persistence_score: np.ndarray | None = None
    extension_zscore: np.ndarray | None = None
    q_effective: float | np.ndarray | None = None


def bars_per_day(index: pd.Index | Sequence[float] | np.ndarray) -> float:
    """Bars per calendar day, from the median spacing of the first 20k bars.

    Median, not mean: weekends, holidays and data gaps are large positive
    outliers in a diff of trading timestamps, and a mean would inflate the
    spacing (and so deflate every day-denominated window) in proportion to how
    much history is loaded. Returns `DEFAULT_BARS_PER_DAY` when the spacing
    cannot be measured, and never returns less than 1.0 -- a bar coarser than
    a day still means "at least one bar per day" for window purposes.
    """
    if isinstance(index, pd.DatetimeIndex):
        seconds = index[:20_000].asi8.astype(float) / 1e9
    else:
        seconds = np.asarray(index, dtype=float)[:20_000]
    if seconds.size < 3:
        return DEFAULT_BARS_PER_DAY
    diffs = np.diff(seconds)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return DEFAULT_BARS_PER_DAY
    bar_seconds = float(np.median(diffs))
    if not np.isfinite(bar_seconds) or bar_seconds <= 0:
        return DEFAULT_BARS_PER_DAY
    return max(1.0, _SECONDS_PER_DAY / bar_seconds)


def bars_for_days(days: float, bpd: float, floor: int = MIN_NOISE_BARS) -> int:
    """Convert a horizon in days to a whole number of bars on this series."""
    try:
        d = float(days)
    except (TypeError, ValueError):
        d = DEFAULT_NOISE_DAYS
    if not np.isfinite(d) or d <= 0:
        d = DEFAULT_NOISE_DAYS
    return max(floor, int(round(d * max(bpd, 1.0))))


def kalman_constant_velocity(
    observations: np.ndarray, *, q: float | np.ndarray = DEFAULT_Q
) -> tuple[np.ndarray, np.ndarray]:
    """Run the constant-velocity filter, returning (level, velocity) per bar.

    Initialised at `level = observations[0]`, `velocity = 0`, `P = I`: the
    filter is told the first price and nothing about the trend, which is
    exactly what is known before any second observation exists.
    Supports either scalar process noise `q` or a 1D array of point-in-time `q` values.
    """
    z = np.asarray(observations, dtype=float)
    n = z.size
    level_out = np.zeros(n, dtype=float)
    slope_out = np.zeros(n, dtype=float)
    if n == 0:
        return level_out, slope_out

    q_arr = np.asarray(q, dtype=float)
    is_q_arr = q_arr.ndim > 0 and q_arr.size == n

    level, velocity = float(z[0]), 0.0
    p11, p12, p22 = 1.0, 0.0, 1.0
    for i in range(n):
        qi = float(q_arr[i]) if is_q_arr else float(q)
        # Predict: x = F x, P = F P F' + Q. Every right-hand side below reads
        # the PRE-update covariance, which is why p11 is written before p12
        # and p12 before p22.
        level += velocity
        p11 += 2.0 * p12 + p22 + qi
        p12 += p22
        p22 += qi
        # Update against the observed level.
        s = p11 + 1.0  # innovation variance H P H' + R, with R = 1
        k1, k2 = p11 / s, p12 / s
        resid = z[i] - level
        level += k1 * resid
        velocity += k2 * resid
        # P = (I - K H) P with H = [1, 0]. p22 is written first because it
        # needs the pre-update p12; reordering these three lines silently
        # changes the filter.
        p22 -= k2 * p12
        p12 -= k1 * p12
        p11 -= k1 * p11
        level_out[i] = level
        slope_out[i] = velocity
    return level_out, slope_out


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    """Trailing sample standard deviation; NaN until `window` bars exist."""
    return (
        pd.Series(values)
        .rolling(window, min_periods=window)
        .std()
        .to_numpy(dtype=float)
    )


def _walk_positions(
    score: np.ndarray, *, entry_z: float, exit_z: float, allow_short: bool
) -> tuple[list[KalmanTrade], bool]:
    """Hysteresis state machine: decide at bar i, fill at bar i+1.

    Returns the round trips plus a flag for whether the last one was still
    open on the final bar. A trade open at the end is closed at the last
    fillable bar rather than dropped -- a backtest that silently discards its
    open position reports the win rate of a strategy nobody could have traded
    -- but the flag keeps that forced close distinguishable from a real exit.
    """
    n = score.size
    trades: list[KalmanTrade] = []
    entry_i: int | None = None
    direction = "long"

    for i in range(n - 1):
        if entry_i is None:
            if score[i] > entry_z:
                entry_i, direction = i + 1, "long"
            elif allow_short and score[i] < -entry_z:
                entry_i, direction = i + 1, "short"
        else:
            done = score[i] < exit_z if direction == "long" else score[i] > -exit_z
            if done:
                trades.append(KalmanTrade(entry_i=entry_i, exit_i=i + 1, direction=direction))
                entry_i = None

    open_at_end = False
    if entry_i is not None and entry_i < n - 1:
        trades.append(KalmanTrade(entry_i=entry_i, exit_i=n - 1, direction=direction))
        open_at_end = True

    return trades, open_at_end


def kalman_trend(
    close: pd.Series | np.ndarray | Sequence[float],
    *,
    q: float = DEFAULT_Q,
    noise_days: float = DEFAULT_NOISE_DAYS,
    entry_z: float = DEFAULT_ENTRY_Z,
    exit_z: float = DEFAULT_EXIT_Z,
    allow_short: bool = False,
    bpd: float | None = None,
    adaptive_vol_scaling: bool = False,
) -> KalmanTrendResult:
    """Filter a close series and reconstruct the trades the thresholds imply.

    `close` may be a pandas Series (its DatetimeIndex is used to measure the
    bar spacing) or a bare array, in which case `bpd` must be supplied or the
    daily default is assumed. Non-positive prices are rejected rather than
    log-transformed into NaN, because a NaN entering the filter propagates
    through every later bar and would surface as an empty chart with no
    explanation.
    When `adaptive_vol_scaling=True`, dynamically calibrates process noise `q`
    and noise window based on trailing realized volatility to eliminate phase lag
    on high-volatility names while preserving stability on indices.
    """
    if isinstance(close, pd.Series):
        prices = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
        measured = bpd if bpd is not None else bars_per_day(close.index)
    else:
        prices = np.asarray(close, dtype=float)
        measured = bpd if bpd is not None else DEFAULT_BARS_PER_DAY

    if prices.size == 0:
        raise ValueError("close must contain at least one priced bar")
    if not np.all(np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("close must be strictly positive and finite (log price is taken)")

    q_effective: float | np.ndarray = float(q)
    effective_noise_days = float(noise_days)
    if adaptive_vol_scaling and prices.size >= 10:
        log_px = np.log(prices)
        rets = np.diff(log_px, prepend=log_px[0])
        # Trailing 20d volatility shifted 1 bar to guarantee strict causality (no look-ahead)
        vol_s = (
            pd.Series(rets)
            .rolling(20, min_periods=5)
            .std()
            .shift(1)
            .fillna(0.015)
            .to_numpy(dtype=float)
        )
        ann_vol = vol_s * np.sqrt(252.0 * float(measured))
        q_effective = np.clip(float(q) * np.maximum(1.0, (ann_vol / 0.20) ** 2), float(q), 5e-4)
        med_vol = float(np.median(ann_vol))
        if med_vol > 0.30:
            scale_factor = min(1.0, 0.35 / med_vol)
            effective_noise_days = max(5.0, float(noise_days) * scale_factor)

    noise_bars = bars_for_days(effective_noise_days, measured)
    level, slope = kalman_constant_velocity(np.log(prices), q=q_effective)
    noise = _rolling_std(slope, noise_bars)
    with np.errstate(invalid="ignore", divide="ignore"):
        score = np.where(np.isfinite(noise) & (noise > 0), slope / noise, 0.0)
    score = np.nan_to_num(score, nan=0.0, posinf=0.0, neginf=0.0)

    # Extension z-score: distance from log price to filtered level, normalized by rolling residual std
    resid = np.log(prices) - level
    resid_std = _rolling_std(resid, noise_bars)
    with np.errstate(invalid="ignore", divide="ignore"):
        ext_score = np.where(np.isfinite(resid_std) & (resid_std > 0), resid / resid_std, 0.0)
    ext_score = np.nan_to_num(ext_score, nan=0.0, posinf=0.0, neginf=0.0)

    trades, open_at_end = _walk_positions(
        score, entry_z=float(entry_z), exit_z=float(exit_z), allow_short=bool(allow_short)
    )

    # Classify trend states per bar
    trend_state = np.empty(prices.size, dtype=object)
    trend_state[score > 1.5] = "BULLISH_ACCELERATING"
    trend_state[(score > 0.5) & (score <= 1.5)] = "BULLISH_TREND"
    trend_state[(score >= -0.5) & (score <= 0.5)] = "FLAT_NEUTRAL"
    trend_state[(score >= -1.5) & (score < -0.5)] = "BEARISH_TREND"
    trend_state[score < -1.5] = "BEARISH_ACCELERATING"

    # Compute persistence count
    persistence = np.ones(prices.size, dtype=int)
    for i in range(1, prices.size):
        if trend_state[i] == trend_state[i - 1]:
            persistence[i] = persistence[i - 1] + 1
        else:
            persistence[i] = 1

    persistence_score = np.minimum(1.0, persistence / 10.0).astype(float)

    return KalmanTrendResult(
        level=level,
        slope=slope,
        noise=noise,
        score=score,
        trades=tuple(trades),
        open_at_end=open_at_end,
        noise_bars=noise_bars,
        bars_per_day=float(measured),
        velocity=slope,
        velocity_zscore=score,
        velocity_noise=noise,
        trend_state=trend_state,
        persistence=persistence,
        persistence_score=persistence_score,
        extension_zscore=ext_score,
        q_effective=q_effective,
    )


def position_state(result: KalmanTrendResult, n: int) -> np.ndarray:
    """Per-bar position: +1 long, -1 short, 0 flat. Held from fill to fill."""
    state = np.zeros(n, dtype=np.int8)
    for t in result.trades:
        state[t.entry_i : t.exit_i] = 1 if t.direction == "long" else -1
    return state
