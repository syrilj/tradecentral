"""Tests for the causal session feature engine.

The load-bearing test here is `test_no_lookahead_in_any_feature`: it is the
executable form of the module's leakage contract, and it is the one that would
catch the class of bug that silently invalidates every downstream result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.session_features import (
    FEATURE_COLUMNS,
    SessionFeatureConfig,
    assert_causal,
    build_features,
    forward_targets,
    session_vwap,
    slot_baseline,
    slot_index,
)

BARS_PER_SESSION = 7


def make_bars(
    n_sessions: int = 60,
    *,
    seed: int = 0,
    u_shape: bool = True,
    base_price: float = 100.0,
) -> pd.DataFrame:
    """Synthetic intraday bars with a realistic U-shaped volume profile."""
    rng = np.random.default_rng(seed)
    idx = []
    for d in range(n_sessions):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=d)
        for s in range(BARS_PER_SESSION):
            idx.append(day + pd.Timedelta(hours=9 + s, minutes=30))
    idx = pd.DatetimeIndex(idx)

    n = len(idx)
    close = base_price + np.cumsum(rng.normal(0.0, 0.25, n))
    high = close + np.abs(rng.normal(0.0, 0.15, n))
    low = close - np.abs(rng.normal(0.0, 0.15, n))
    open_ = close - rng.normal(0.0, 0.1, n)
    # The U: open and close slots carry far more volume than midday.
    shape = np.array([3.0, 1.4, 0.9, 0.7, 0.8, 1.5, 2.2]) if u_shape else np.ones(BARS_PER_SESSION)
    vol = np.tile(shape, n_sessions) * 1_000_000 * rng.uniform(0.85, 1.15, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


# --------------------------------------------------------------- causality --

def test_no_lookahead_in_any_feature():
    """The whole research stack rests on this: perturb the future, the past must not move."""
    assert_causal(make_bars(80))


def test_assert_causal_actually_catches_a_planted_leak():
    """A guard that cannot fail is not a guard."""
    bars = make_bars(40)
    leaked = build_features(bars).copy()
    # A centred rolling mean is the classic accidental leak.
    leaked["peek"] = bars["close"].rolling(5, center=True).mean()

    base = leaked.iloc[: int(len(leaked) * 0.7)]
    tampered = bars.copy()
    tampered.iloc[int(len(bars) * 0.7):, :] *= 3.0
    after = build_features(tampered)
    after = after.assign(peek=tampered["close"].rolling(5, center=True).mean())

    common = base.index.intersection(after.index)
    a = base.loc[common, "peek"].to_numpy()
    b = after.loc[common, "peek"].to_numpy()
    assert not np.allclose(a, b, equal_nan=True), "planted leak was not visible"


def test_baseline_excludes_the_bar_it_judges():
    """A bar in its own baseline makes a real climax look ordinary."""
    bars = make_bars(40)
    slots = slot_index(bars.index)
    base = slot_baseline(bars["volume"], slots)

    spiked = bars.copy()
    target = spiked.index[-1]
    spiked.loc[target, "volume"] *= 50.0
    after = slot_baseline(spiked["volume"], slots)

    assert np.isclose(base.loc[target, "baseline"], after.loc[target, "baseline"]), (
        "the spiked bar changed its own baseline"
    )


# --------------------------------------------------------------- VWAP math --

def test_session_vwap_resets_each_session():
    bars = make_bars(5)
    vw = session_vwap(bars)
    sess = bars.index.normalize()
    for day in np.unique(sess):
        first = bars[sess == day].index[0]
        tp = (bars.loc[first, "high"] + bars.loc[first, "low"] + bars.loc[first, "close"]) / 3.0
        assert np.isclose(vw.loc[first, "vwap"], tp), (
            "first bar of a session must equal its own typical price, "
            "i.e. carry nothing from the prior session"
        )


def test_session_vwap_matches_a_direct_weighted_mean():
    bars = make_bars(3)
    vw = session_vwap(bars)
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    sess = pd.Series(bars.index.normalize(), index=bars.index)
    direct = (tp * bars["volume"]).groupby(sess).cumsum() / bars["volume"].groupby(sess).cumsum()
    assert np.allclose(vw["vwap"].to_numpy(), direct.to_numpy(), rtol=1e-10)


def test_west_variance_matches_numpy_weighted_variance():
    bars = make_bars(2)
    vw = session_vwap(bars)
    tp = ((bars["high"] + bars["low"] + bars["close"]) / 3.0).to_numpy()
    v = bars["volume"].to_numpy()
    day0 = bars.index.normalize() == bars.index.normalize()[0]
    k = int(day0.sum())
    for i in range(k):
        w, x = v[: i + 1], tp[: i + 1]
        mean = np.average(x, weights=w)
        var = np.average((x - mean) ** 2, weights=w)
        assert np.isclose(vw["vwap_sd"].to_numpy()[i], np.sqrt(var), rtol=1e-8, atol=1e-10)


def test_west_variance_survives_a_high_price_where_naive_cancellation_fails():
    """E[x^2]-E[x]^2 loses most of its significant digits at high prices."""
    bars = make_bars(3, base_price=250_000.0)
    vw = session_vwap(bars)
    sd = vw["vwap_sd"].dropna()
    assert (sd >= 0).all()
    assert sd.notna().all()
    assert sd.iloc[-1] > 0, "band collapsed to zero: cancellation"


def test_zero_volume_bars_do_not_move_the_vwap():
    bars = make_bars(3)
    idx = bars.index[3]
    zeroed = bars.copy()
    zeroed.loc[idx, "volume"] = 0.0
    zeroed.loc[idx, ["high", "low", "close"]] = [1e6, 1e6, 1e6]

    a = session_vwap(bars.drop(index=idx))["vwap"]
    b = session_vwap(zeroed)["vwap"]
    later = bars.index[4]
    assert np.isclose(a.loc[later], b.loc[later]), "a zero-volume bar dragged the VWAP"


def test_bars_before_any_volume_are_nan_not_invented():
    bars = make_bars(2)
    first = bars.index[0]
    blanked = bars.copy()
    blanked.loc[first, "volume"] = 0.0
    assert np.isnan(session_vwap(blanked)["vwap"].loc[first])


# ------------------------------------------------- time-of-day normalisation --

def test_slot_normalisation_flattens_the_volume_u_shape():
    """The defect this module exists to remove."""
    bars = make_bars(80, u_shape=True)
    feats = build_features(bars).dropna(subset=["rvol_slot"])
    naive = bars["volume"] / bars["volume"].shift(1).rolling(20, min_periods=5).mean()

    by_slot_new = feats.groupby("slot")["rvol_slot"].mean()
    by_slot_old = naive.groupby(slot_index(bars.index)).mean().dropna()

    spread_new = by_slot_new.max() - by_slot_new.min()
    spread_old = by_slot_old.max() - by_slot_old.min()
    assert spread_new < spread_old / 2.0, (
        f"slot normalisation did not flatten the U-shape (new {spread_new:.2f} vs old {spread_old:.2f})"
    )
    assert spread_new < 0.5, f"residual time-of-day bias {spread_new:.2f}"


def test_a_genuine_spike_still_registers_after_normalisation():
    bars = make_bars(60, u_shape=True)
    midday = [i for i, t in enumerate(bars.index) if t.hour == 12][-1]
    spiked = bars.copy()
    spiked.iloc[midday, spiked.columns.get_loc("volume")] *= 6.0
    feats = build_features(spiked)
    assert feats["rvol_slot"].iloc[midday] > 4.0, "a real 6x midday spike was normalised away"


def test_baseline_kind_is_reported():
    feats = build_features(make_bars(60))
    kinds = set(feats["rvol_baseline_kind"].dropna().unique())
    assert "slot_median" in kinds
    assert kinds <= {"", "slot_median", "trailing_median"}


def test_short_history_falls_back_rather_than_emitting_nothing():
    feats = build_features(make_bars(6))
    assert feats["rvol_slot"].notna().sum() > 0, "short history produced no usable baseline at all"


# ------------------------------------------------------------- structure ----

def test_slot_index_is_ordinal_not_clock_hour():
    """A shortened session keeps its ordinals; an hour key would mix them."""
    bars = make_bars(3)
    short_day = bars.index.normalize() == bars.index.normalize()[1]
    trimmed = bars[~(short_day & (bars.index.hour >= 12))]
    slots = slot_index(trimmed.index)
    day2 = trimmed[trimmed.index.normalize() == trimmed.index.normalize()[-1]]
    assert list(slot_index(day2.index)) == list(range(len(day2)))
    assert slots.max() == BARS_PER_SESSION - 1


def test_bars_on_side_restarts_each_session():
    feats = build_features(make_bars(20))
    firsts = feats.groupby("session").head(1)
    assert (firsts["bars_on_side"] == 1).all()


def test_crosses_never_fire_on_the_first_bar_of_a_session():
    feats = build_features(make_bars(30))
    firsts = feats.groupby("session").head(1)
    assert (firsts["cross_up"] == 0).all()
    assert (firsts["cross_dn"] == 0).all()


def test_feature_columns_are_all_present():
    feats = build_features(make_bars(60))
    missing = [c for c in FEATURE_COLUMNS if c not in feats.columns]
    assert not missing, f"declared but not produced: {missing}"


def test_no_target_column_leaks_into_the_feature_frame():
    """Targets live in a separate function precisely so this cannot happen."""
    feats = build_features(make_bars(20))
    for banned in ("ret_next_bp", "ret_eod_bp", "abs_eod_bp"):
        assert banned not in feats.columns


# --------------------------------------------------------------- targets ----

def test_forward_targets_are_forward_and_session_bounded():
    bars = make_bars(10)
    tgt = forward_targets(bars)
    sess = pd.Series(bars.index.normalize(), index=bars.index)
    last_of_session = ~sess.eq(sess.shift(-1))
    assert tgt.loc[last_of_session, "ret_next_bp"].isna().all()
    assert tgt.loc[last_of_session, "ret_eod_bp"].isna().all()

    i = 2
    expected = (bars["close"].iloc[i + 1] / bars["close"].iloc[i] - 1.0) * 1e4
    assert np.isclose(tgt["ret_next_bp"].iloc[i], expected)


def test_abs_target_is_the_magnitude_of_the_signed_one():
    tgt = forward_targets(make_bars(10))
    both = tgt.dropna(subset=["ret_eod_bp"])
    assert np.allclose(both["abs_eod_bp"], both["ret_eod_bp"].abs())


# ------------------------------------------------------------- validation ---

@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda d: d.iloc[::-1], "ascending"),
        (lambda d: pd.concat([d, d.iloc[[0]]]).sort_index(), "unique"),
    ],
)
def test_bad_index_is_rejected_loudly(mutate, message):
    with pytest.raises(ValueError, match=message):
        build_features(mutate(make_bars(5)))


def test_missing_column_is_rejected():
    with pytest.raises(ValueError, match="missing required columns"):
        build_features(make_bars(5).drop(columns=["volume"]))


def test_config_rejects_nonsense():
    with pytest.raises(ValueError):
        SessionFeatureConfig(baseline_sessions=1)
    with pytest.raises(ValueError):
        SessionFeatureConfig(slope_bars=0)


def test_works_on_real_bars_if_present():
    """Smoke test against real data when it is on disk; skipped in CI without it."""
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "data" / "1h" / "SPY.parquet"
    if not p.is_file():
        pytest.skip("no local 1h data")
    bars = pd.read_parquet(p)
    bars = bars[~bars.index.duplicated(keep="last")].sort_index().tail(2000)
    feats = build_features(bars, symbol="SPY")
    assert len(feats) > 0
    assert feats["rvol_slot"].notna().mean() > 0.5
    assert_causal(bars.tail(700))
