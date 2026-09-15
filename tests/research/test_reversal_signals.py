"""Reversal features: Pine parity on hand-checkable cases, and no lookahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.research import reversal_signals as rs
from edge.research import reversal_study as study


def _bars(n: int = 900, seed: int = 1, intraday: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if intraday:
        days = pd.bdate_range("2024-01-02", periods=n // 7 + 2)
        idx = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(hours=h) for d in days for h in range(7)])[:n]
    else:
        idx = pd.bdate_range("2015-01-02", periods=n)
    ret = rng.normal(0, 0.006, n) + 0.004 * np.sin(np.arange(n) / 40.0)
    close = 100 * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.004, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.lognormal(13, 0.4, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def test_st_macd_ha_body_matches_pine_recurrence():
    df = _bars(300)
    m = rs.st_macd_ha(df)
    x = m["macd_raw"]
    # ohlc4 of (x[1], max, min, x) collapses to the mean of x[1] and x
    assert np.allclose(m["macd_ha_c"].iloc[2:], ((x.shift(1) + x) / 2).iloc[2:])
    # ha open is the previous bar's (open + close) / 2
    expect_open = ((m["macd_ha_o"] + m["macd_ha_c"]) / 2).shift(1)
    assert np.allclose(m["macd_ha_o"].iloc[3:], expect_open.iloc[3:])


def test_os_signal_requires_flip_below_threshold():
    df = _bars(900, seed=4)
    m = rs.st_macd_ha(df)
    os_rows = m[m["macd_os"]]
    assert (os_rows["macd_ha_l"] < -100).all()
    assert (os_rows["macd_ha_c"] > os_rows["macd_ha_o"]).all()


def test_swing_vwap_direction_and_anchor():
    df = _bars(900, seed=2)
    sw = rs.swing_anchored_vwap(df)
    flips = sw[sw["swing_flip"]]
    assert len(flips) > 2
    for ts, row in flips.iterrows():
        pos = df.index.get_loc(ts)
        if row["swing_dir"] > 0:
            # up flip happens on a new 50-bar high, anchored at the swing low
            assert row["swing_high_pos"] == pos
            assert row["svwap_anchor_pos"] == row["swing_low_pos"]
        else:
            assert row["swing_low_pos"] == pos
            assert row["svwap_anchor_pos"] == row["swing_high_pos"]
    started = sw["svwap"].notna()
    assert (sw.loc[started, "svwap"] > df["low"].min() * 0.5).all()


@pytest.mark.parametrize("intraday", [True, False])
def test_features_have_no_lookahead(intraday):
    """Appending future bars must not change any feature on earlier bars."""
    df = _bars(900 if intraday else 700, seed=7, intraday=intraday)
    cut = len(df) - 60
    params = rs.FeatureParams(profile_sessions=20 if intraday else 60, profile_bins=40 if intraday else 30)
    full = rs.build_features(df, params)
    part = rs.build_features(df.iloc[:cut], params)
    cols = [c for c in part.columns if part[c].dtype != object]
    a = full.iloc[:cut][cols].astype(float)
    b = part[cols].astype(float)
    diff = (a - b).abs().where(~(a.isna() & b.isna()), 0.0)
    bad = diff.max()
    assert bad.max() < 1e-7, bad[bad >= 1e-7].to_dict()


def test_profile_uses_prior_sessions_only():
    df = _bars(700, seed=3)
    prof = rs.session_profiles(df, lookback_sessions=20, bins=40)
    days = df.index.normalize().unique()
    day = days[30]
    window = df[(df.index.normalize() >= days[10]) & (df.index.normalize() < day)]
    poc, val, vah = rs.profile_levels(window, 40)
    got = prof.loc[df.index.normalize() == day].iloc[0]
    assert got["poc"] == pytest.approx(poc)
    assert val <= poc <= vah


def test_htf_alignment_uses_previous_day():
    df = _bars(300, seed=5)
    daily = df.resample("D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    ctx = pd.DataFrame({"x": np.arange(len(daily), dtype=float)}, index=daily.index)
    aligned = rs.align_htf(df.index, ctx, "D")
    for ts in df.index[50:60]:
        prev = ctx.index[ctx.index < ts.normalize()][-1]
        assert aligned.at[ts, "x"] == ctx.at[prev, "x"]


def test_triple_barrier_orders_touches():
    idx = pd.bdate_range("2020-01-01", periods=6)
    df = pd.DataFrame(
        {"open": [10] * 6, "high": [10, 10.5, 12.1, 10, 10, 10], "low": [10, 9.5, 10, 8, 10, 10], "close": [10] * 6, "volume": [1] * 6},
        index=idx,
        dtype=float,
    )
    atr = pd.Series(1.0, index=idx)
    y = rs.triple_barrier(df, atr, horizon=3, up_mult=2.0, dn_mult=1.0, side=1)
    assert y.iloc[0] == 1.0  # +2 on bar 2 before -1 (bar 3)
    y_short = rs.triple_barrier(df, atr, horizon=3, up_mult=2.0, dn_mult=1.0, side=-1)
    assert y_short.iloc[0] == 0.0  # +1 adverse on bar 2 (12.1) before -2 on bar 3


def test_directional_frame_mirrors():
    df = _bars(900, seed=9)
    f = rs.build_features(df)
    f = f.join(rs.align_htf(df.index, rs.htf_context(rs.weekly_bars(df.resample("D").last().dropna())), "D"))
    for c in ("mkt_macd", "mkt_off_high_atr", "mkt_off_low_atr", "mkt_ret5_atr", "mkt_ret10_pct", "breadth_below", "breadth_above"):
        f[c] = 0.0
    bull = study.directional_frame(f, 1)
    bear = study.directional_frame(f, -1)
    assert list(bull.columns) == list(bear.columns)
    assert set(study.FEATURES) <= set(bull.columns)
    ok = f["svwap_dist_atr"].notna()
    assert np.allclose(bull.loc[ok, "svwap_dist_dir"], -bear.loc[ok, "svwap_dist_dir"])
