from __future__ import annotations

import pandas as pd
import pytest

from edge.research.robustness import (
    monte_carlo_robustness,
    oof_underlying_robustness_diagnostics,
)


def _oof() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=20)
    rows = []
    for date in dates:
        rows.extend([
            {"timestamp": date, "symbol": "AAA", "volatility_regime": "LOW", "position": 1, "gross_return": .01},
            {"timestamp": date, "symbol": "BBB", "volatility_regime": "HIGH", "position": -1, "gross_return": -.002},
        ])
    return pd.DataFrame(rows).set_index(["timestamp", "symbol"])


def test_oof_cost_stresses_are_deterministic_date_aggregated_and_supplemental_only() -> None:
    first = oof_underlying_robustness_diagnostics(_oof(), n_bootstrap=300, seed=7)
    second = oof_underlying_robustness_diagnostics(_oof(), n_bootstrap=300, seed=7)
    assert first == second
    assert first["scope"] == "development_oof_underlying_supplemental_diagnostic"
    assert first["option_profitability"] == "not_evaluated"
    assert first["live_portfolio_drawdown"] == "not_evaluated"
    stresses = first["cost_stresses"]
    assert [item["round_trip_cost_bps"] for item in stresses] == [10.0, 20.0, 30.0]
    assert stresses[0]["date_aggregated_net_expectancy"] == pytest.approx(.003)
    assert stresses[-1]["date_aggregated_net_expectancy"] == pytest.approx(.001)
    assert stresses[0]["date_aggregated_net_expectancy"] > stresses[-1]["date_aggregated_net_expectancy"]
    assert stresses[0]["date_block_bootstrap_ci95"]["n_dates"] == 20


def test_symbol_and_regime_positive_pnl_concentration_flags_are_explicit() -> None:
    report = oof_underlying_robustness_diagnostics(_oof(), n_bootstrap=100)
    item = report["cost_stresses"][0]
    assert item["symbol_positive_pnl_concentration"]["flagged"] is True
    assert item["regime_positive_pnl_concentration"]["flagged"] is True
    assert item["symbol_positive_pnl_concentration"]["largest_positive_pnl_share"] > .5


def test_holdout_and_invalid_oof_rows_are_rejected_without_reading_them() -> None:
    held_out = _oof().reset_index().assign(partition="terminal_holdout").set_index(["timestamp", "symbol"])
    with pytest.raises(ValueError, match="holdout"):
        oof_underlying_robustness_diagnostics(held_out)
    invalid = _oof().copy(); invalid.iloc[0, invalid.columns.get_loc("position")] = 0
    with pytest.raises(ValueError, match="flat"):
        oof_underlying_robustness_diagnostics(invalid)


def _net_oof() -> pd.DataFrame:
    """Date-aggregated net returns with a known positive mean and spread."""
    dates = pd.bdate_range("2025-01-02", periods=40)
    rows = []
    for date in dates:
        rows.extend([
            {"timestamp": date, "symbol": "AAA", "net_return": .004},
            {"timestamp": date, "symbol": "BBB", "net_return": .002},
        ])
    return pd.DataFrame(rows).set_index(["timestamp", "symbol"])


def test_monte_carlo_robustness_is_deterministic_and_supplemental_only() -> None:
    first = monte_carlo_robustness(_net_oof(), n_simulations=300, seed=7)
    second = monte_carlo_robustness(_net_oof(), n_simulations=300, seed=7)
    assert first == second
    assert first["scope"] == "development_oof_supplemental_diagnostic"
    assert first["option_profitability"] == "not_evaluated"
    assert first["live_portfolio_drawdown"] == "not_evaluated"
    assert first["promotion_criteria"] == "unchanged"
    assert first["n_dates"] == 40
    drawdowns = first["max_drawdown_distribution"]
    assert drawdowns["n_simulations"] == 300
    assert drawdowns["worst_case"] <= drawdowns["expected_max_drawdown"] <= 0.0
    assert drawdowns["worst_case"] <= drawdowns["worst_95pct"] <= 0.0
    assert first["probability_of_loss_by_holding_period"]["21"] == pytest.approx(0.0)
    assert first["annual_compounded_return_ci"] is None  # 40 dates < 252


def test_monte_carlo_robustness_reports_loss_probability_and_annual_ci() -> None:
    dates = pd.bdate_range("2024-01-02", periods=300)
    rows = []
    for date in dates:
        rows.append({"timestamp": date, "symbol": "AAA", "net_return": .0005})
    report = monte_carlo_robustness(
        pd.DataFrame(rows).set_index(["timestamp", "symbol"]),
        n_simulations=200, seed=0,
    )
    assert report["n_dates"] == 300
    assert report["annual_compounded_return_ci"]["periods"] == 252
    assert report["annual_compounded_return_ci"]["lower_bound"] > 0.0
    assert report["probability_of_loss_by_holding_period"]["252"] == pytest.approx(0.0)


def test_monte_carlo_robustness_rejects_holdout_rows() -> None:
    held_out = _net_oof().reset_index().assign(partition="terminal_holdout").set_index(["timestamp", "symbol"])
    with pytest.raises(ValueError, match="holdout"):
        monte_carlo_robustness(held_out)
