"""Contract tests for the Kalman constant-velocity trend filter.

The properties pinned here are the ones whose breakage would be invisible on a
chart: causality (no look-ahead), the exact covariance recursion, and the
day-denominated noise window. A filter that quietly peeks one bar ahead still
draws a plausible line.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.kalman_trend import (
    DEFAULT_BARS_PER_DAY,
    MIN_NOISE_BARS,
    bars_for_days,
    bars_per_day,
    kalman_constant_velocity,
    kalman_trend,
    position_state,
)


def _ramp(n: int = 400, drift: float = 0.003, noise: float = 0.0, seed: int = 11) -> pd.Series:
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0, noise, n) if noise else np.zeros(n)
    log_px = np.log(100.0) + np.cumsum(np.full(n, drift) + shocks)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.Series(np.exp(log_px), index=idx)


def _reference_filter(z: np.ndarray, q: float) -> tuple[np.ndarray, np.ndarray]:
    """Independent matrix implementation of the same model, used to catch a
    transcription slip in the scalar recursion (the p11/p12/p22 write order is
    load-bearing and silently wrong if reordered)."""
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    Q = q * np.eye(2)
    H = np.array([[1.0, 0.0]])
    R = np.array([[1.0]])
    x = np.array([[z[0]], [0.0]])
    P = np.eye(2)
    levels, slopes = np.zeros(z.size), np.zeros(z.size)
    for i in range(z.size):
        x = F @ x
        P = F @ P @ F.T + Q
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        x = x + K @ (np.array([[z[i]]]) - H @ x)
        P = (np.eye(2) - K @ H) @ P
        levels[i], slopes[i] = float(x[0, 0]), float(x[1, 0])
    return levels, slopes


def test_scalar_recursion_matches_matrix_kalman():
    z = np.log(_ramp(n=250, noise=0.01).to_numpy())
    level, slope = kalman_constant_velocity(z, q=1e-6)
    ref_level, ref_slope = _reference_filter(z, 1e-6)
    assert np.allclose(level, ref_level, atol=1e-12)
    assert np.allclose(slope, ref_slope, atol=1e-12)


def test_velocity_converges_to_the_true_drift():
    drift = 0.004
    _, slope = kalman_constant_velocity(np.log(_ramp(n=800, drift=drift).to_numpy()), q=1e-5)
    # Late in a noiseless ramp the filter should be reading the drift back,
    # not a smoothed fraction of it.
    assert slope[-1] == pytest.approx(drift, rel=0.05)


def test_filter_is_causal_truncating_history_cannot_change_the_past():
    full = _ramp(n=500, noise=0.012)
    cut = 300
    a = kalman_trend(full, q=1e-6, noise_days=20, entry_z=1.0, exit_z=0.0)
    b = kalman_trend(full.iloc[:cut], q=1e-6, noise_days=20, entry_z=1.0, exit_z=0.0)
    assert np.allclose(a.slope[:cut], b.slope, atol=1e-12)
    assert np.allclose(a.score[:cut], b.score, atol=1e-12, equal_nan=True)


def test_entries_fill_the_bar_after_the_signal():
    result = kalman_trend(_ramp(n=500, noise=0.012), entry_z=1.0, exit_z=0.0, allow_short=True)
    assert result.trades, "expected at least one round trip on a trending series"
    for t in result.trades:
        signal_i = t.entry_i - 1
        assert signal_i >= 0
        crossed = (
            result.score[signal_i] > 1.0 if t.direction == "long" else result.score[signal_i] < -1.0
        )
        assert crossed, f"trade filled at {t.entry_i} without a crossing at {signal_i}"
        assert t.exit_i > t.entry_i


def test_score_is_zero_until_the_noise_window_is_full():
    result = kalman_trend(_ramp(n=200, noise=0.01), noise_days=20)
    assert result.noise_bars == 20
    assert np.all(result.score[: result.noise_bars - 1] == 0.0)
    assert np.all(np.isnan(result.noise[: result.noise_bars - 1]))


def test_long_only_never_opens_a_short():
    falling = _ramp(n=400, drift=-0.004, noise=0.01)
    long_only = kalman_trend(falling, entry_z=1.0, exit_z=0.0, allow_short=False)
    both = kalman_trend(falling, entry_z=1.0, exit_z=0.0, allow_short=True)
    assert all(t.direction == "long" for t in long_only.trades)
    assert any(t.direction == "short" for t in both.trades)


def test_open_position_is_closed_at_the_last_bar_and_flagged():
    result = kalman_trend(_ramp(n=400, drift=0.004), entry_z=1.0, exit_z=0.0)
    assert result.open_at_end is True
    assert result.trades[-1].exit_i == 399


def test_hysteresis_holds_through_a_dip_a_symmetric_threshold_would_cut():
    series = _ramp(n=400, noise=0.011)
    tight = kalman_trend(series, entry_z=1.0, exit_z=1.0)
    loose = kalman_trend(series, entry_z=1.0, exit_z=0.0)
    assert len(loose.trades) <= len(tight.trades)


def test_noise_window_is_denominated_in_days_not_bars():
    n = 3000
    hourly_idx = pd.date_range("2023-01-02 09:00", periods=n, freq="h")
    hourly = pd.Series(np.exp(np.log(50.0) + np.cumsum(np.full(n, 0.0002))), index=hourly_idx)
    result = kalman_trend(hourly, noise_days=20)
    # 20 days of hourly bars is ~480 bars, not 20.
    assert result.bars_per_day == pytest.approx(24.0)
    assert result.noise_bars == 480


def test_bars_per_day_and_window_conversion_edges():
    daily = pd.date_range("2024-01-02", periods=50, freq="B")
    assert bars_per_day(daily) == pytest.approx(1.0)
    # Too few stamps to measure spacing -> documented fallback, not a crash.
    assert bars_per_day(pd.DatetimeIndex([])) == DEFAULT_BARS_PER_DAY
    # A sub-day horizon must never collapse the sd window to 1-2 bars.
    assert bars_for_days(0.1, 1.0) == MIN_NOISE_BARS
    assert bars_for_days(float("nan"), 1.0) == 20


def test_position_state_marks_held_bars_only():
    result = kalman_trend(_ramp(n=400, noise=0.011), entry_z=1.0, exit_z=0.0, allow_short=True)
    state = position_state(result, 400)
    for t in result.trades:
        assert np.all(state[t.entry_i : t.exit_i] != 0)
    # The exit bar itself is flat: the fill happens at its open.
    last = result.trades[-1]
    if last.exit_i < 399:
        assert state[last.exit_i] == 0 or any(
            t.entry_i == last.exit_i for t in result.trades
        )


@pytest.mark.parametrize("bad", [[100.0, 0.0, 101.0], [100.0, -1.0, 101.0], [100.0, np.nan]])
def test_non_positive_or_missing_prices_are_rejected_not_logged_to_nan(bad):
    with pytest.raises(ValueError):
        kalman_trend(pd.Series(bad, index=pd.date_range("2024-01-02", periods=len(bad))))
