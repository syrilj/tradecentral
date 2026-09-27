"""Sealed out-of-sample capital proof: fit before the window, verdict from the live gates."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.decision_tree_backtest import (
    build_panel,
    evaluate_sealed_live_capital,
    fit_decision_model,
    judge_live_capital,
)
from research.live_edge import evaluate_walk_forward_gates
from research.quant_core import sharpe as annualized_sharpe
from research.statistics import newey_west_tstat


def _prices(periods: int, seed: int, *, start: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.01, size=periods)
    close = 50.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.001, size=periods))
    high = np.maximum(open_, close) * (1.0 + rng.random(periods) * 0.003)
    low = np.minimum(open_, close) * (1.0 - rng.random(periods) * 0.003)
    volume = rng.integers(1_000_000, 3_000_000, size=periods).astype(float)
    index = pd.bdate_range(start, periods=periods)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def test_out_of_sample_labels_do_not_change_the_fit_or_threshold() -> None:
    bars = {
        "AAA": _prices(180, 3, start="2023-01-03"),
        "BBB": _prices(180, 5, start="2023-01-03"),
        "CCC": _prices(180, 8, start="2023-01-03"),
    }
    panel = build_panel(bars, history_bars=None)
    oos_start = pd.Timestamp(panel["target_date"].max()) - pd.Timedelta(days=40)
    original = fit_decision_model(panel, oos_start=oos_start)
    leaked = panel.copy()
    mask = (
        pd.to_datetime(leaked["target_date"]).dt.normalize() >= pd.Timestamp(oos_start).normalize()
    )
    leaked.loc[mask, "target_up"] = 1 - leaked.loc[mask, "target_up"].to_numpy()
    leaked.loc[mask, "target_return"] = -leaked.loc[mask, "target_return"].to_numpy()
    refit = fit_decision_model(leaked, oos_start=oos_start)

    assert original.training_end < original.oos_start
    assert original.fingerprint() == refit.fingerprint()
    assert refit.oos_start == pd.Timestamp(oos_start).normalize().date().isoformat()


def test_verdict_passes_only_when_the_live_capital_checks_pass() -> None:
    dates = pd.bdate_range("2023-01-03", "2024-12-31")
    trades = []
    for index, session in enumerate(dates):
        signal = session - pd.tseries.offsets.BDay(1)
        gross = 0.008 + 0.0015 * np.sin(index / 7.0)
        trades.append(
            {
                "symbol": "SPY",
                "signal_date": signal.date().isoformat(),
                "session_date": session.date().isoformat(),
                "action": "buy",
                "gross_return": float(gross),
                "entry_open": 100.0,
                "exit_close": 100.0 * (1.0 + float(gross)),
                "volume": 80_000_000.0,
                "volatility_regime": "LOW" if index % 2 == 0 else "HIGH",
            }
        )
    passed = judge_live_capital(trades, session_dates=dates, trial_count=15)
    assert passed["verdict"] == "pass"
    assert passed["all_checks_passed"] is True
    assert passed["decision_authorized"] is False
    assert passed["order"] is None
    assert passed["allow_live_order_submission"] is False
    assert (passed["verdict"] == "pass") is passed["all_checks_passed"]

    daily = passed["checks"]["newey_west_t"]["daily_returns"]
    assert newey_west_tstat(daily) == passed["checks"]["newey_west_t"]["t"]
    assert (
        annualized_sharpe(pd.Series(daily, dtype=float))
        == passed["checks"]["cost_stress"]["1.0x"]["sharpe"]
    )
    folds = [
        float("nan") if value is None else value
        for value in passed["checks"]["walk_forward"]["fold_sharpes"]
    ]
    assert evaluate_walk_forward_gates(folds).passed is passed["checks"]["walk_forward"]["passed"]

    losers = [dict(trade, gross_return=-0.02, exit_close=98.0) for trade in trades[:8]]
    failed = judge_live_capital(losers, session_dates=dates[:8], trial_count=15)
    assert failed["verdict"] == "not-ready"
    assert failed["all_checks_passed"] is False
    assert failed["decision_authorized"] is False
    assert failed["order"] is None
    assert (failed["verdict"] == "pass") is failed["all_checks_passed"]


def test_short_history_is_not_ready_and_does_not_authorize_an_order() -> None:
    bars = {
        "AAA": _prices(70, 2, start="2024-06-03"),
        "BBB": _prices(70, 4, start="2024-06-03"),
    }
    report = evaluate_sealed_live_capital(universe=bars, history_bars=None)
    assert report["verdict"] == "not-ready"
    assert report["decision_authorized"] is False
    assert report["order"] is None
    assert report["allow_live_order_submission"] is False
    assert report["window"]["holdout_used_for_training"] is False
    assert report["window"]["training_end"] < report["window"]["oos_start"]
    assert report["window"]["execution_lag_bars"] >= 1
    panel = build_panel(bars, history_bars=None)
    model = fit_decision_model(panel, oos_start=report["window"]["oos_start"])
    assert report["model"]["parameters"] == model.parameters
    assert report["model"]["confidence_threshold"] == model.confidence_threshold


def test_recorded_history_live_capital_stays_unauthorized() -> None:
    report = evaluate_sealed_live_capital()
    assert report["verdict"] in {"pass", "not-ready"}
    assert (report["verdict"] == "pass") is report["all_checks_passed"]
    assert report["decision_authorized"] is False
    assert report["order"] is None
    assert report["allow_live_order_submission"] is False
    assert report["window"]["holdout_used_for_training"] is False
    assert report["window"]["training_end"] < report["window"]["oos_start"]
    assert report["window"]["execution_lag_bars"] >= 1
    assert report["sample"]["observations"] > 0
    assert report["sample"]["unscorable"] < report["sample"]["observations"]
    if report["window"]["supported"] is False:
        assert report["verdict"] == "not-ready"
