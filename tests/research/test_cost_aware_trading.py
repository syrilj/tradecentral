"""
Unit tests for Workstream 2: Cost-Aware Trading Decisions, Net Edge Gating, & Portfolio Limits.
"""

from __future__ import annotations

import pytest

try:
    from edge.research.costs import DynamicCostModel
    from edge.research.portfolio import (
        PortfolioLimitsConfig,
        compute_expected_net_edge,
        apply_cost_aware_sizing,
    )
except ImportError:
    from research.portfolio import (
        PortfolioLimitsConfig,
        compute_expected_net_edge,
        apply_cost_aware_sizing,
    )


def test_expected_net_edge_calculation():
    # alpha = +0.0050 (50 bps return)
    # cost = 10 bps (0.0010)
    # std = 0.0020, k = 1.0 -> 20 bps
    # expected net edge = 50 bps - 10 bps - 20 bps = +20 bps (0.0020)
    edge = compute_expected_net_edge(
        alpha_hat=0.0050,
        estimated_cost_bps=10.0,
        forecast_std=0.0020,
        safety_margin_k=1.0,
    )
    assert edge == pytest.approx(0.0020, abs=1e-6)

    # Negative net edge case: alpha 15 bps, cost 10 bps, k*std 10 bps -> net edge = -5 bps
    neg_edge = compute_expected_net_edge(
        alpha_hat=0.0015,
        estimated_cost_bps=10.0,
        forecast_std=0.0010,
        safety_margin_k=1.0,
    )
    assert neg_edge < 0.0


def test_cost_aware_sizing_filters_low_edge():
    target_w = {"AAPL": 0.05, "MSFT": 0.05}
    curr_w = {"AAPL": 0.0, "MSFT": 0.0}

    # AAPL has high alpha (100 bps), MSFT has tiny alpha (2 bps)
    alphas = {"AAPL": 0.0100, "MSFT": 0.0002}
    stds = {"AAPL": 0.0010, "MSFT": 0.0010}
    advs = {"AAPL": 10_000_000.0, "MSFT": 10_000_000.0}

    filtered, rejections = apply_cost_aware_sizing(
        target_weights=target_w,
        current_weights=curr_w,
        alphas=alphas,
        forecast_stds=stds,
        adv_usd=advs,
    )

    assert filtered["AAPL"] > 0.0
    assert filtered["MSFT"] == 0.0
    assert "Insufficient net edge" in rejections["MSFT"]


def test_no_trade_zone_rebalance_buffer():
    # Small weight shift: target 0.0501 vs current 0.0500 -> delta is 0.0001 (1 bps)
    target_w = {"AAPL": 0.0501}
    curr_w = {"AAPL": 0.0500}
    alphas = {"AAPL": 0.0100}
    stds = {"AAPL": 0.0010}
    advs = {"AAPL": 10_000_000.0}

    filtered, _ = apply_cost_aware_sizing(
        target_weights=target_w,
        current_weights=curr_w,
        alphas=alphas,
        forecast_stds=stds,
        adv_usd=advs,
    )

    # Weight retained at current_w (0.0500) rather than rebalancing to 0.0501
    assert filtered["AAPL"] == 0.0500


def test_portfolio_limits_enforced():
    # AAPL target weight 0.25 exceeds max_position_weight 0.10
    target_w = {"AAPL": 0.25}
    curr_w = {"AAPL": 0.0}
    alphas = {"AAPL": 0.0200}
    stds = {"AAPL": 0.0010}
    advs = {"AAPL": 50_000_000.0}

    limits = PortfolioLimitsConfig(max_position_weight=0.10)
    filtered, _ = apply_cost_aware_sizing(
        target_weights=target_w,
        current_weights=curr_w,
        alphas=alphas,
        forecast_stds=stds,
        adv_usd=advs,
        limits=limits,
    )

    assert filtered["AAPL"] == pytest.approx(0.10, abs=1e-5)


def test_cash_holding_allowed():
    # Only 1 stock has a strong signal; sum of weights is 0.05 < 1.0 (remainder in cash)
    target_w = {"AAPL": 0.05}
    curr_w = {"AAPL": 0.0}
    alphas = {"AAPL": 0.0200}
    stds = {"AAPL": 0.0010}
    advs = {"AAPL": 10_000_000.0}

    filtered, _ = apply_cost_aware_sizing(
        target_weights=target_w,
        current_weights=curr_w,
        alphas=alphas,
        forecast_stds=stds,
        adv_usd=advs,
    )

    total_exposure = sum(abs(w) for w in filtered.values())
    assert total_exposure == 0.05  # 95% cash
