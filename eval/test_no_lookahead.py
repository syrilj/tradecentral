"""
Property tests proving edge/eval/harness.py cannot leak df.iloc[t] backward into
rows for index < t, and that its asof resolution never lands on the target bar.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from . import harness


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_synthetic_df(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=0.0004, scale=0.018, size=n)
    close = 100.0 * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, 0.004, size=n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, 0.004, size=n)))
    volume = rng.integers(1_000_000, 5_000_000, size=n).astype(float)
    dates = pd.bdate_range("2020-01-02", periods=n)
    return pd.DataFrame({
        "timestamps": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _toy_predict_fn(hist: pd.DataFrame) -> Dict[str, float]:
    """A deterministic, pure function of hist only — mean drift +/- full-window
    std, so any bar smuggled into hist changes the prediction."""
    closes = hist["close"].to_numpy(dtype=float)
    last = float(closes[-1])
    if closes.size > 1:
        drift = float(np.mean(np.diff(closes)))
        spread = max(float(np.std(closes)), 1e-6)
    else:
        drift = 0.0
        spread = abs(last) * 0.01 + 1e-6
    p50 = last + drift
    return {"p10": p50 - 1.2816 * spread, "p50": p50, "p90": p50 + 1.2816 * spread}


# ---------------------------------------------------------------------------
# 1. The flagship property: mutating bar t cannot change any row for t' < t
# ---------------------------------------------------------------------------

def test_mutating_future_bar_leaves_earlier_rows_byte_identical():
    df = _make_synthetic_df(160)
    cfg = harness.WalkForwardConfig(lookback=30, min_lookback=20, n_days=None)
    rows_before = harness.run_walkforward(_toy_predict_fn, df, cfg)

    assert len(rows_before) > 0
    for r in rows_before:
        assert r["dir_hit"] in (0, 1)
        assert r["in_pi80"] in (0, 1)

    all_t = sorted(r["t"] for r in rows_before)
    probe_ts = sorted({all_t[len(all_t) // 4], all_t[len(all_t) // 2], all_t[-3]})

    for probe_t in probe_ts:
        mutated = df.copy(deep=True)
        mutated.loc[probe_t, "close"] = mutated.loc[probe_t, "close"] * 1000.0

        rows_after = harness.run_walkforward(_toy_predict_fn, mutated, cfg)

        before_prefix = [r for r in rows_before if r["t"] < probe_t]
        after_prefix = [r for r in rows_after if r["t"] < probe_t]

        assert len(before_prefix) > 0
        assert before_prefix == after_prefix


# ---------------------------------------------------------------------------
# 2. The bug class found in production: bakeoff_trend_v5.py did
#      asof = target_date; hist = df[df.timestamps <= asof]
#    which resolves asof to df.iloc[t] (the target bar) instead of df.iloc[t-1].
# ---------------------------------------------------------------------------

def test_asof_resolution_is_prior_bar_never_target_bar():
    df = _make_synthetic_df(80)

    for t in (25, 40, 55, 79):
        correct_asof = harness.resolve_asof_timestamp(df, t)
        assert correct_asof == df.iloc[t - 1][harness.DATE_COL]
        assert correct_asof != df.iloc[t][harness.DATE_COL]

        # bakeoff_trend_v5.py's actual bug, reproduced inline (Kronos/ untouched):
        #   asof = target_date; hist = df[df.timestamps <= asof]
        buggy_asof = pd.Timestamp(df.iloc[t][harness.DATE_COL])
        buggy_hist = df[df[harness.DATE_COL] <= buggy_asof]
        correct_hist = df[df[harness.DATE_COL] <= correct_asof]

        assert len(buggy_hist) == t + 1
        assert len(correct_hist) == t
        assert buggy_hist.iloc[-1][harness.DATE_COL] == df.iloc[t][harness.DATE_COL]
        assert correct_hist.iloc[-1][harness.DATE_COL] == df.iloc[t - 1][harness.DATE_COL]

        # the algebraic identity from the audit: last_ret == actual_ret, exactly,
        # whenever hist wrongly includes the target bar.
        buggy_closes = buggy_hist[harness.PRICE_COL].to_numpy(dtype=float)
        buggy_last_ret = buggy_closes[-1] / buggy_closes[-2] - 1.0
        actual_ret = float(df.iloc[t][harness.PRICE_COL]) / float(df.iloc[t - 1][harness.PRICE_COL]) - 1.0
        assert buggy_last_ret == actual_ret


# ---------------------------------------------------------------------------
# 3. ACCEPTANCE demo: point test 1's mutation methodology at an inline,
#    old-style leaky hist window (forgets the upper bound at t) and confirm it
#    WOULD have failed — proof the property test has teeth, not tautological.
#    Kronos/ is not touched; the leaky path is reimplemented locally.
# ---------------------------------------------------------------------------

def _leaky_hist_window(df: pd.DataFrame, t: int, lb: int) -> pd.DataFrame:
    return df.iloc[t - lb:].reset_index(drop=True)  # BUG: no upper bound at t


def _leaky_run_walkforward(predict_fn, df: pd.DataFrame, lookback: int, min_lookback: int):
    rows = []
    for t in harness.eval_indices(len(df), min_lookback, None):
        lb = min(lookback, t)
        if lb < min_lookback:
            continue
        leaky_hist = _leaky_hist_window(df, t, lb)
        pred = predict_fn(leaky_hist)
        last_close = float(df.iloc[t - 1][harness.PRICE_COL])
        actual_close = float(df.iloc[t][harness.PRICE_COL])
        actual_ret = actual_close / last_close - 1.0 if last_close else 0.0
        pred_ret_p50 = float(pred["p50"]) / last_close - 1.0 if last_close else 0.0
        rows.append({
            "t": int(t),
            "pred_p50": float(pred["p50"]),
            "pred_ret_p50": pred_ret_p50,
            "dir_hit": harness._dir_hit(pred_ret_p50, actual_ret),
        })
    return rows


def test_mutation_property_would_have_caught_an_unbounded_hist_window():
    df = _make_synthetic_df(160)
    lookback, min_lookback = 30, 20

    leaky_before = _leaky_run_walkforward(_toy_predict_fn, df, lookback, min_lookback)
    all_t = sorted(r["t"] for r in leaky_before)
    probe_t = all_t[len(all_t) // 2]

    mutated = df.copy(deep=True)
    mutated.loc[probe_t, "close"] = mutated.loc[probe_t, "close"] * 1000.0

    leaky_after = _leaky_run_walkforward(_toy_predict_fn, mutated, lookback, min_lookback)
    leaky_before_prefix = [r for r in leaky_before if r["t"] < probe_t]
    leaky_after_prefix = [r for r in leaky_after if r["t"] < probe_t]

    assert len(leaky_before_prefix) > 0
    assert leaky_before_prefix != leaky_after_prefix  # the leak: earlier rows moved

    cfg = harness.WalkForwardConfig(lookback=lookback, min_lookback=min_lookback)
    real_before = harness.run_walkforward(_toy_predict_fn, df, cfg)
    real_after = harness.run_walkforward(_toy_predict_fn, mutated, cfg)
    real_before_prefix = [r for r in real_before if r["t"] < probe_t]
    real_after_prefix = [r for r in real_after if r["t"] < probe_t]

    assert real_before_prefix == real_after_prefix  # the real harness: unmoved
