"""The live scorer and the backtest row are the same decision at the same timestamp."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.decision_tree_backtest import (
    build_panel,
    fit_decision_model,
    run_last_week_backtest,
    score_asof,
    score_dates,
    score_realtime_decision,
)


def _prices(periods: int, seed: int, *, start: str = "2024-01-02") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0004, 0.012, size=periods)
    close = 80.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.002, size=periods))
    high = np.maximum(open_, close) * (1.0 + rng.random(periods) * 0.004)
    low = np.minimum(open_, close) * (1.0 - rng.random(periods) * 0.004)
    volume = rng.integers(800_000, 2_500_000, size=periods).astype(float)
    index = pd.bdate_range(start, periods=periods)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _universe() -> dict[str, pd.DataFrame]:
    return {
        "SPCX": _prices(140, 7),
        "QQQ": _prices(140, 11),
        "IWM": _prices(140, 19),
    }


def test_realtime_matches_backtest_row_and_ignores_the_trade_session() -> None:
    bars = _universe()
    report = run_last_week_backtest(universe=bars)
    row = report["focus"]["rows"][-1]
    first = score_realtime_decision("SPCX", row["signal_asof"], universe=bars)
    second = score_realtime_decision("SPCX", row["signal_asof"], universe=bars)

    assert second == first
    assert first["action"] == row["action"]
    assert first["confidence"] == row["confidence"]
    assert first["trade"] == row["active"]
    assert first["decision_authorized"] is False
    assert first["order"] is None
    assert first["execution_lag_bars"] >= 1

    mutated = {symbol: frame.copy() for symbol, frame in bars.items()}
    session = pd.Timestamp(row["session_date"])
    mutated["SPCX"].loc[session, "close"] *= 1.8
    mutated["SPCX"].loc[session, "high"] = mutated["SPCX"].loc[session, ["open", "close"]].max()
    after = score_realtime_decision("SPCX", row["signal_asof"], universe=mutated)
    assert after["action"] == first["action"]
    assert after["confidence"] == first["confidence"]
    assert after["trade"] == first["trade"]


def test_missing_or_incomplete_bars_abstain_instead_of_trading() -> None:
    bars = _universe()
    report = run_last_week_backtest(universe=bars)
    signal = pd.Timestamp(report["focus"]["rows"][-1]["signal_asof"])
    broken = bars["SPCX"].copy()
    broken.loc[signal, "close"] = np.nan
    missing = score_realtime_decision("SPCX", signal, universe=bars, bars=broken)
    assert missing["trade"] is False
    assert missing["abstain"] is True
    assert missing["action"] is None
    assert missing["order"] is None

    dropped = bars["SPCX"].drop(index=signal)
    absent = score_realtime_decision("SPCX", signal, universe=bars, bars=dropped)
    assert absent["trade"] is False
    assert absent["abstain"] is True
    assert absent["action"] is None

    clock = pd.Timestamp(signal).tz_localize("America/New_York") + pd.Timedelta(hours=11)
    incomplete = score_realtime_decision("SPCX", signal, universe=bars, clock=clock)
    assert incomplete["reason"] == "incomplete_session"
    assert incomplete["trade"] is False
    assert incomplete["action"] is None


def test_later_bar_does_not_change_an_earlier_asof_score() -> None:
    bars = _universe()
    panel = build_panel(bars, history_bars=None)
    model = fit_decision_model(panel, oos_start=panel["target_date"].max())
    history = bars["SPCX"]
    early = history.index[50]
    later = history.index[-1]
    alone = score_asof(history, early, model, session_complete=True)
    batched = score_dates(history, [early, later], model, session_complete=True)[0]
    assert batched["action"] == alone["action"]
    assert batched["confidence"] == alone["confidence"]
    assert batched["trade"] == alone["trade"]

    truncated = score_asof(history.loc[:early], early, model, session_complete=True)
    assert truncated == alone

    corrupted = history.copy()
    corrupted.loc[later, "close"] *= 2.5
    again = score_asof(corrupted, early, model, session_complete=True)
    assert again["action"] == alone["action"]
    assert again["confidence"] == alone["confidence"]
    assert again["trade"] == alone["trade"]
    assert again == score_asof(corrupted, early, model, session_complete=True)
