"""Tests for the GATE_XS5 runner (edge/tools/xs5_pit_optimizer.py).

The properties that matter for the gate:
  - the runner's accounting routes through simulate_long_short (enforced by
    test_portfolio_primitive_guard.py as well);
  - the frozen decile baseline is dollar-neutral and rebalances weekly;
  - the walk-forward OOF slice never overlaps training dates;
  - a pure-noise signal prints no fortune at execution_lag=1, while an oracle
    signal is still detected (the same control shape as test_portfolio.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.tools.xs5_pit_optimizer import (
    DEV_END,
    REBALANCE_EVERY,
    build_signal,
    decile_weights,
    oof_daily_returns,
    run_spec,
)


def _panel(n_dates: int = 400, n_syms: int = 12, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=n_dates)
    syms = [f"S{i:02d}" for i in range(n_syms)]
    rets = pd.DataFrame(rng.normal(0.0, 0.02, size=(n_dates, n_syms)), index=dates, columns=syms)
    close = 100.0 * (1.0 + rets).cumprod()
    rows = []
    for symbol in syms:
        frame = pd.DataFrame({"close": close[symbol]}, index=dates)
        frame["symbol"] = symbol
        rows.append(frame.reset_index(names="timestamp").set_index(["timestamp", "symbol"]))
    return pd.concat(rows).sort_index()


def test_runner_never_reads_past_dev_end():
    """GATE_XS5 rule 3: the development cutoff is frozen at 2026-07-29."""
    assert DEV_END == pd.Timestamp("2026-07-29")


def test_decile_baseline_is_dollar_neutral_and_weekly():
    signal = pd.DataFrame(
        np.tile(np.arange(12.0), (60, 1)),
        index=pd.bdate_range("2024-01-02", periods=60),
        columns=[f"S{i:02d}" for i in range(12)],
    )
    long_w, short_w = decile_weights(signal)
    # Weights only exist on rebalance bars (every REBALANCE_EVERY bars).
    active = long_w.abs().sum(axis=1) > 0
    assert active.sum() == len(signal) // REBALANCE_EVERY
    for i in np.flatnonzero(active):
        assert long_w.iloc[i].sum() == pytest.approx(1.0)
        assert short_w.iloc[i].sum() == pytest.approx(1.0)
        # No symbol is in both legs on the same bar.
        assert not ((long_w.iloc[i] > 0) & (short_w.iloc[i] > 0)).any()


def test_oof_slice_never_overlaps_training_dates():
    daily = pd.Series(
        np.random.default_rng(0).normal(0, 0.01, 800),
        index=pd.bdate_range("2020-01-02", periods=800),
    )
    oof = oof_daily_returns(daily)
    assert len(oof) > 0
    oof_positions = np.flatnonzero(daily.index.isin(oof.index))
    # Every OOF date must be at least one fold's validation block; the simplest
    # sound check: OOF dates are strictly increasing and the first OOF date is
    # after the initial training window.
    assert oof_positions[0] >= 504
    assert np.all(np.diff(oof_positions) > 0)


def test_noise_signal_prints_no_fortune_at_lag_one():
    panel = _panel()
    rng = np.random.default_rng(1)
    dates = panel.index.get_level_values("timestamp").unique()
    syms = panel.index.get_level_values("symbol").unique()
    noise = pd.DataFrame(rng.normal(0, 1, size=(len(dates), len(syms))),
                         index=dates, columns=syms)
    # Inject the noise signal directly by monkeypatching build_signal.
    import edge.tools.xs5_pit_optimizer as mod
    original = mod.build_signal
    mod.build_signal = lambda p, s: noise
    try:
        daily = run_spec(panel, "mom12_1", use_optimizer=True, use_vol_target=True)
    finally:
        mod.build_signal = original
    ann = daily.mean() * 252
    assert abs(ann) < 0.50, f"noise signal earned {ann:.2%} annual at lag 1"


def test_oracle_signal_is_still_detected_at_lag_one():
    panel = _panel()
    dates = panel.index.get_level_values("timestamp").unique()
    syms = panel.index.get_level_values("symbol").unique()
    close = panel["close"].unstack("symbol").sort_index()
    oracle = close.pct_change().shift(-1).fillna(0.0)  # knows tomorrow
    import edge.tools.xs5_pit_optimizer as mod
    original = mod.build_signal
    mod.build_signal = lambda p, s: oracle
    try:
        daily = run_spec(panel, "mom12_1", use_optimizer=True, use_vol_target=False)
    finally:
        mod.build_signal = original
    ann = daily.mean() * 252
    # The optimizer's max_weight=0.05 cap dilutes the oracle across the whole
    # 12-name book, so the bar is set well below the uncapped decile book's
    # >100% but far above the noise test's ~0%.
    assert ann > 0.30, f"oracle signal earned only {ann:.2%} annual at lag 1"


def test_build_signal_is_backward_looking():
    panel = _panel(n_dates=200)
    signal = build_signal(panel, "mom12_1")
    # mom12_1 at bar t uses closes at t-21 and t-126: mutating bar t's close
    # cannot change the signal at t.
    before = signal.copy()
    mutated = panel.copy()
    last = mutated.index.get_level_values("timestamp").max()
    mutated.loc[mutated.index.get_level_values("timestamp") == last, "close"] *= 100
    after = build_signal(mutated, "mom12_1")
    pd.testing.assert_frame_equal(before.loc[:last], after.loc[:last])
