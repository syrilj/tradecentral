"""Tests for Volatility-Targeted Trend quantitative research model."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research.vol_target_trend import (
    VolTargetTrendResult,
    compute_trade_stats,
    vol_target_trend,
)


def _make_df(prices: np.ndarray, spacing_s: float = 86400.0) -> pd.DataFrame:
    n = len(prices)
    ts = np.arange(n, dtype=float) * spacing_s + 1_700_000_000.0
    return pd.DataFrame({
        "close": prices,
        "open": prices,
        "ts": ts,
    })


def test_vol_target_trend_basic_uptrend():
    """An obvious uptrend generates long trades with positive returns."""
    # 200 bars of steady upward trend with small noise
    np.random.seed(42)
    ramp = np.linspace(100.0, 200.0, 250) + np.random.normal(0, 0.5, 250)
    df = _make_df(ramp)

    result = vol_target_trend(df, target_vol=0.15, lev_cap=3.0, fast_days=5, slow_days=20, vol_days=20)
    assert isinstance(result, VolTargetTrendResult)
    assert result.fast_bars == 5
    assert result.slow_bars == 20
    assert result.vol_bars == 20
    assert len(result.ema_fast) == len(df)
    assert len(result.ann_vol) == len(df)
    assert len(result.leverage) == len(df)
    assert len(result.trades) > 0

    # Uptrend should produce profitable long trades
    stats = compute_trade_stats(result.trades, result.position_state, result.capital)
    assert stats["n_trades"] > 0
    assert stats["win_rate_pct"] is not None and stats["win_rate_pct"] > 50.0
    assert stats["total_pnl"] > 0


def test_vol_target_leverage_inversely_proportional_to_vol():
    """Higher volatility produces lower leverage, respecting the cap."""
    np.random.seed(42)
    # Low-volatility ramp
    low_vol_ramp = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.005, 300)))
    df_low = _make_df(low_vol_ramp)
    res_low = vol_target_trend(df_low, target_vol=0.15, lev_cap=3.0)

    # High-volatility ramp
    high_vol_ramp = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.03, 300)))
    df_high = _make_df(high_vol_ramp)
    res_high = vol_target_trend(df_high, target_vol=0.15, lev_cap=3.0)

    valid_low_lev = res_low.leverage[np.isfinite(res_low.leverage) & (res_low.leverage > 0)]
    valid_high_lev = res_high.leverage[np.isfinite(res_high.leverage) & (res_high.leverage > 0)]

    assert np.mean(valid_low_lev) > np.mean(valid_high_lev)
    assert np.all(valid_low_lev <= 3.0 + 1e-9)
    assert np.all(valid_high_lev <= 3.0 + 1e-9)


def test_vol_target_intraday_bar_scaling():
    """Hourly bars (~3600s) scale fast/slow/vol bar counts by ~24 compared to daily."""
    prices = np.linspace(100, 150, 500)
    df_hourly = _make_df(prices, spacing_s=3600.0)
    res_hourly = vol_target_trend(df_hourly, fast_days=5, slow_days=20, vol_days=20)

    # ~24 bars per day
    assert res_hourly.bars_per_day >= 20.0
    assert res_hourly.fast_bars > 5 * 20
    assert res_hourly.slow_bars > 20 * 20


def test_vol_target_fill_and_no_lookahead():
    """Fills occur at bar i+1 after signal at bar i."""
    np.random.seed(123)
    p = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0] * 10)
    df = _make_df(p)
    res = vol_target_trend(df, fast_days=2, slow_days=4, vol_days=4)

    for t in res.trades:
        assert t.entry_i > 0
        assert t.exit_i > t.entry_i
        # Sizing check: nominal notional matches Capital * leverage
        expected_notional = (res.capital * t.leverage_at_entry / df["close"].iloc[t.entry_i - 1]) * t.entry_px
        assert np.isclose(t.notional, expected_notional, rtol=1e-3)


def test_vol_target_empty_or_invalid():
    """Invalid inputs raise ValueError."""
    with pytest.raises(ValueError):
        vol_target_trend(pd.DataFrame())

    with pytest.raises(ValueError):
        vol_target_trend(pd.DataFrame({"foo": [1, 2, 3]}))
