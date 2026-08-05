"""Property tests for causal volatility-target scaling.

The defect these tests exist to catch is the same one documented in
`test_portfolio.py`, in a volatility costume: a forecast vol computed with a
window ending at (and including) bar `i` already contains bar `i`'s own
return. Sizing bar `i`'s position from that forecast without a shift is the
same one-bar lookahead `research/portfolio.py` measured at +502.58%/yr on
PEAD -- just arrived at through a vol forecast instead of a momentum signal.
`vol_target_scale`'s `execution_lag` shift is the single line this test
file exists to hold accountable; `test_scale_is_causal_wrt_future_close_mutations`
is the headline test for it.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from edge.research.portfolio import simulate_long_short
from edge.research.vol_targeting import (
    VolTargetDiagnostics,
    apply_vol_target,
    ewma_volatility,
    realized_volatility,
    vol_target_diagnostics,
    vol_target_scale,
)


def _panel(n_dates: int = 500, n_syms: int = 24, seed: int = 7):
    """IID returns; no symbol has any forward predictability by construction."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=n_dates)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    rets = pd.DataFrame(rng.normal(0.0, 0.02, size=(n_dates, n_syms)), index=dates, columns=syms)
    close = 100.0 * (1.0 + rets).cumprod()
    return close, rets


def _top_bottom_weights(signal: pd.DataFrame, k: int = 5):
    """Equal-weight long the top k / short the bottom k of `signal` each bar."""
    rank = signal.rank(axis=1, ascending=False)
    n = signal.shape[1]
    long_w = (rank <= k).astype(float) / k
    short_w = (rank > n - k).astype(float) / k
    return long_w, short_w


def _regime_shift_panel(n_dates: int = 800, n_syms: int = 10, seed: int = 3, block: int = 100):
    """Market-wide vol multiplier alternates every `block` bars between a low
    and a high regime, so an unscaled book's realised vol swings well away
    from any fixed target -- this is the fixture that gives vol targeting
    something real to do."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-02", periods=n_dates)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    mult = np.where((np.arange(n_dates) // block) % 2 == 0, 0.5, 3.0)
    base = rng.normal(0.0, 0.01, size=(n_dates, n_syms))
    rets = pd.DataFrame(base * mult[:, None], index=dates, columns=syms)
    close = 100.0 * (1.0 + rets).cumprod()
    return close, rets


# ---------------------------------------------------------------------------
# realized_volatility / ewma_volatility causality
# ---------------------------------------------------------------------------


def test_realized_volatility_uses_only_bars_le_i() -> None:
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0.0, 0.01, 100), index=pd.bdate_range("2021-01-04", periods=100))
    a = realized_volatility(returns, window=20)

    mutated = returns.copy()
    i = 60
    mutated.iloc[i + 1 :] = mutated.iloc[i + 1 :] * 9.0  # mutate strictly after bar i
    b = realized_volatility(mutated, window=20)

    pd.testing.assert_series_equal(a.iloc[: i + 1], b.iloc[: i + 1])
    # sanity: the mutation actually changed something downstream, otherwise
    # this test would pass vacuously
    assert not a.iloc[i + 1 :].equals(b.iloc[i + 1 :])


def test_ewma_volatility_uses_only_bars_le_i() -> None:
    rng = np.random.default_rng(2)
    returns = pd.Series(rng.normal(0.0, 0.01, 100), index=pd.bdate_range("2021-01-04", periods=100))
    a = ewma_volatility(returns, halflife=10.0)

    mutated = returns.copy()
    i = 60
    mutated.iloc[i + 1 :] = mutated.iloc[i + 1 :] * 9.0
    b = ewma_volatility(mutated, halflife=10.0)

    pd.testing.assert_series_equal(a.iloc[: i + 1], b.iloc[: i + 1])
    assert not a.iloc[i + 1 :].equals(b.iloc[i + 1 :])


def test_realized_volatility_warmup_is_nan_with_min_periods_window() -> None:
    returns = pd.Series(np.full(30, 0.01), index=pd.bdate_range("2021-01-04", periods=30))
    vol = realized_volatility(returns, window=20)
    assert vol.iloc[:19].isna().all()
    assert vol.iloc[19:].notna().all()


# ---------------------------------------------------------------------------
# vol_target_scale
# ---------------------------------------------------------------------------


def test_execution_lag_below_one_bar_is_rejected() -> None:
    """Same-bar sizing is not a tunable option -- it is unrepresentable, same
    as `simulate_long_short`."""
    forecast = pd.Series([0.10, 0.12, 0.09, 0.11], index=pd.bdate_range("2021-01-04", periods=4))
    for bad in (0, -1):
        with pytest.raises(ValueError, match="execution_lag"):
            vol_target_scale(forecast_vol=forecast, execution_lag=bad)


def test_scale_is_causal_wrt_future_close_mutations() -> None:
    """Headline causality test: mutating `close` strictly after bar i must
    not change `apply_vol_target`'s scaled weights at or before bar i.

    Verified this test actually fails when it should by temporarily removing
    the `.shift(execution_lag)` inside `vol_target_scale` during development
    (using the raw, unshifted `clipped` series instead) -- the assertion
    below failed immediately, as expected, and the shift was restored before
    this file was finalized.
    """
    close, rets = _panel(n_dates=400, n_syms=12, seed=5)
    long_w, short_w = _top_bottom_weights(rets)

    scaled_long_a, scaled_short_a = apply_vol_target(
        long_weights=long_w, short_weights=short_w, close=close, window=20, target_vol=0.10
    )

    mutated_close = close.copy()
    i = 300
    mutated_close.iloc[i + 1 :] = mutated_close.iloc[i + 1 :] * 1.0 + 5.0  # mutate strictly after bar i

    scaled_long_b, scaled_short_b = apply_vol_target(
        long_weights=long_w, short_weights=short_w, close=mutated_close, window=20, target_vol=0.10
    )

    pd.testing.assert_frame_equal(scaled_long_a.iloc[: i + 1], scaled_long_b.iloc[: i + 1])
    pd.testing.assert_frame_equal(scaled_short_a.iloc[: i + 1], scaled_short_b.iloc[: i + 1])
    # sanity: confirm the mutation actually did something downstream
    assert not scaled_long_a.iloc[i + 1 :].equals(scaled_long_b.iloc[i + 1 :])


@pytest.mark.parametrize("method", ["realized", "ewma"])
def test_scale_is_causal_for_both_methods(method: str) -> None:
    close, rets = _panel(n_dates=200, n_syms=8, seed=9)
    long_w, short_w = _top_bottom_weights(rets, k=3)

    a_long, a_short = apply_vol_target(
        long_weights=long_w, short_weights=short_w, close=close, method=method, window=20, halflife=15.0
    )
    mutated = close.copy()
    i = 150
    mutated.iloc[i + 1 :] *= 2.5
    b_long, b_short = apply_vol_target(
        long_weights=long_w, short_weights=short_w, close=mutated, method=method, window=20, halflife=15.0
    )
    pd.testing.assert_frame_equal(a_long.iloc[: i + 1], b_long.iloc[: i + 1])
    pd.testing.assert_frame_equal(a_short.iloc[: i + 1], b_short.iloc[: i + 1])


def test_scale_lags_a_vol_step_by_exactly_execution_lag() -> None:
    """A hand-built step in forecast_vol must reappear in `scale` exactly
    `execution_lag` bars later -- not one bar early, not one bar late."""
    idx = pd.bdate_range("2021-01-04", periods=40)
    forecast = pd.Series([0.10] * 20 + [0.40] * 20, index=idx)  # vol steps up at position 20
    lag = 3
    scale = vol_target_scale(forecast_vol=forecast, target_vol=0.10, max_leverage=10.0, execution_lag=lag)

    step_bar = 20 + lag
    # the first `lag` bars are 0.0 -- shift has nothing to shift in yet, same
    # "missing -> flat" rule as any other warm-up, not part of what this test
    # is checking
    assert (scale.iloc[:lag] == 0.0).all()
    # from bar `lag` up to (not including) the reaction bar, scale still
    # reflects the old, low-vol forecast (scale == target/0.10 == 1.0)
    assert np.allclose(scale.iloc[lag:step_bar].to_numpy(), 1.0)
    # the reaction bar and everything after reflect the new forecast
    # (scale == target/0.40 == 0.25) -- appears exactly on time, not late
    assert np.allclose(scale.iloc[step_bar:].to_numpy(), 0.25)


def test_scale_falls_after_a_realistic_vol_regime_shift() -> None:
    """On a returns series whose realised vol genuinely regime-shifts from
    low to high, the resulting scale is materially lower deep in the
    high-vol regime than deep in the low-vol regime."""
    close, rets = _regime_shift_panel(n_dates=400, n_syms=6, block=200)
    book_returns = rets.mean(axis=1)  # simple equal-weight proxy book
    vol = realized_volatility(book_returns, window=20)
    scale = vol_target_scale(forecast_vol=vol, target_vol=0.10, max_leverage=10.0, execution_lag=1)

    # deep inside each block, away from the transition and warm-up
    low_regime_scale = scale.iloc[100:180].mean()
    high_regime_scale = scale.iloc[300:380].mean()
    assert high_regime_scale < low_regime_scale


def test_warmup_rows_are_flat_not_nan_not_full_size() -> None:
    rng = np.random.default_rng(4)
    returns = pd.Series(rng.normal(0.0, 0.01, 40), index=pd.bdate_range("2021-01-04", periods=40))
    vol = realized_volatility(returns, window=20)  # NaN for first 19 bars
    lag = 1
    scale = vol_target_scale(forecast_vol=vol, target_vol=0.10, execution_lag=lag)

    # first (window - 1) + lag == 20 bars must be exactly 0.0
    warmup = scale.iloc[:20]
    assert (warmup == 0.0).all()
    assert not scale.isna().any()
    assert not (warmup == 1.0).any()


def test_leverage_clipping_respects_both_bounds() -> None:
    idx = pd.bdate_range("2021-01-04", periods=5)
    # engineered so raw target/vol blows past both bounds
    vol = pd.Series([0.001, 0.001, 100.0, 100.0, 0.05], index=idx)
    scale = vol_target_scale(
        forecast_vol=vol, target_vol=0.10, max_leverage=2.0, min_leverage=0.3, execution_lag=1
    )
    expected = pd.Series([0.0, 2.0, 2.0, 0.3, 0.3], index=idx)
    pd.testing.assert_series_equal(scale, expected, check_names=False)


# ---------------------------------------------------------------------------
# apply_vol_target
# ---------------------------------------------------------------------------


def test_unknown_method_raises() -> None:
    close, rets = _panel(n_dates=60, n_syms=6)
    long_w, short_w = _top_bottom_weights(rets, k=2)
    with pytest.raises(ValueError, match="method"):
        apply_vol_target(long_weights=long_w, short_weights=short_w, close=close, method="garbage")
    with pytest.raises(ValueError, match="method"):
        vol_target_diagnostics(long_weights=long_w, short_weights=short_w, close=close, method="garbage")


def test_unexpected_keyword_raises() -> None:
    close, rets = _panel(n_dates=60, n_syms=6)
    long_w, short_w = _top_bottom_weights(rets, k=2)
    with pytest.raises(TypeError):
        apply_vol_target(long_weights=long_w, short_weights=short_w, close=close, max_leverge=3.0)


def test_output_plugs_into_simulate_long_short_unmodified() -> None:
    close, rets = _panel()
    long_w, short_w = _top_bottom_weights(rets)
    scaled_long, scaled_short = apply_vol_target(long_weights=long_w, short_weights=short_w, close=close)

    # must be accepted with no reshaping, exactly like a hand-built weight frame
    res = simulate_long_short(long_weights=scaled_long, short_weights=scaled_short, close=close, execution_lag=1)
    assert res.n_bars == len(close)
    assert scaled_long.index.equals(close.index)
    assert scaled_long.columns.equals(long_w.columns)


def test_scaled_book_realised_vol_is_closer_to_target_than_unscaled() -> None:
    """The module's reason to exist: vol targeting should pull realised vol
    toward the target more than leaving the book unscaled."""
    close, rets = _regime_shift_panel()
    n_syms = close.shape[1]
    long_w = pd.DataFrame(1.0 / n_syms, index=close.index, columns=close.columns)
    short_w = pd.DataFrame(0.0, index=close.index, columns=close.columns)

    target = 0.15
    scaled_long, scaled_short = apply_vol_target(
        long_weights=long_w, short_weights=short_w, close=close,
        target_vol=target, window=20, max_leverage=5.0,
    )

    unscaled = simulate_long_short(
        long_weights=long_w, short_weights=short_w, close=close, execution_lag=1, cost_per_side=0.0
    )
    scaled = simulate_long_short(
        long_weights=scaled_long, short_weights=scaled_short, close=close, execution_lag=1, cost_per_side=0.0
    )

    assert abs(scaled.annual_volatility - target) < abs(unscaled.annual_volatility - target)


# ---------------------------------------------------------------------------
# VolTargetDiagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_as_dict_survives_json_dumps() -> None:
    close, rets = _panel(n_dates=300, n_syms=10)
    long_w, short_w = _top_bottom_weights(rets, k=3)

    diag = vol_target_diagnostics(
        long_weights=long_w, short_weights=short_w, close=close, target_vol=0.10, window=20, max_leverage=3.0
    )
    payload = diag.as_dict()
    dumped = json.dumps(payload)  # must not raise
    reloaded = json.loads(dumped)

    assert isinstance(payload["n_bars"], int)
    assert reloaded["n_bars"] == len(close)
    assert 0.0 <= payload["frac_at_leverage_cap"] <= 1.0
    assert 0.0 <= payload["frac_flat_warmup"] <= 1.0
    # warm-up rows exist (window=20) so some bars must be flat
    assert payload["frac_flat_warmup"] > 0.0


def test_diagnostics_as_dict_converts_nan_to_none() -> None:
    diag = VolTargetDiagnostics(
        target_vol=0.10,
        unscaled_realized_vol=float("nan"),
        scaled_realized_vol=0.11,
        mean_leverage=0.9,
        median_leverage=0.9,
        max_leverage_applied=2.0,
        frac_at_leverage_cap=0.1,
        frac_flat_warmup=0.05,
        n_bars=100,
    )
    payload = diag.as_dict()
    assert payload["unscaled_realized_vol"] is None
    assert payload["scaled_realized_vol"] == pytest.approx(0.11)
    json.dumps(payload)  # must not raise -- NaN would break this


def test_diagnostics_leverage_stats_are_sane() -> None:
    close, rets = _regime_shift_panel(n_dates=400, n_syms=8, block=100)
    n_syms = close.shape[1]
    long_w = pd.DataFrame(1.0 / n_syms, index=close.index, columns=close.columns)
    short_w = pd.DataFrame(0.0, index=close.index, columns=close.columns)

    diag = vol_target_diagnostics(
        long_weights=long_w, short_weights=short_w, close=close,
        target_vol=0.10, window=20, max_leverage=2.0, min_leverage=0.0,
    )
    assert diag.max_leverage_applied <= 2.0 + 1e-9
    assert diag.median_leverage <= diag.max_leverage_applied + 1e-9
    assert math.isfinite(diag.unscaled_realized_vol)
    assert math.isfinite(diag.scaled_realized_vol)
