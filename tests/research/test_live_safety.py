"""
Unit tests for Workstream 7: Live Safety Gates & Risk Reconciler.
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

try:
    from edge.research.safety import (
        StrategyState,
        SafetyConfig,
        validate_live_safety_state,
        regime_risk_multiplier,
    )
    from edge.research.decision import make_decision
    from edge.research.live_edge import (
        evaluate_walk_forward_gates,
        apply_regime_to_predictions,
        select_approved_model_version,
    )
except ImportError:
    from research.safety import (
        StrategyState,
        SafetyConfig,
        validate_live_safety_state,
        regime_risk_multiplier,
    )
    from research.decision import make_decision
    from research.live_edge import (
        evaluate_walk_forward_gates,
        apply_regime_to_predictions,
        select_approved_model_version,
    )


def test_stale_quote_blocks_new_orders():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    stale_quote_ts = pd.Timestamp("2026-08-01 15:55:00")  # 300s old > 60s max

    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={"AAPL": 0.0},
        last_quote_ts={"AAPL": stale_quote_ts},
    )

    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"pred_AAPL": 0.05},
        config=SafetyConfig(max_quote_stale_seconds=60.0),
    )

    assert not report.is_safe
    assert any("stale" in r for r in report.rejection_reasons)
    assert report.risk_scale == 0.0


def test_unresolved_orders_block_new_orders():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={"AAPL": 0.0},
        unresolved_orders=["ORD_12345"],  # Pending order
    )

    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"pred_AAPL": 0.05},
    )

    assert not report.is_safe
    assert any("Unresolved broker orders" in r for r in report.rejection_reasons)


def test_drawdown_limit_breach_blocks_new_orders():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=80_000.0,
        position_ledger={"AAPL": 0.0},
        strategy_peak_equity=100_000.0,
        current_equity=80_000.0,  # 20% drawdown > 15% max
    )

    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"pred_AAPL": 0.05},
        config=SafetyConfig(max_strategy_drawdown_pct=0.15),
    )

    assert not report.is_safe
    assert any("Strategy drawdown limit breached" in r for r in report.rejection_reasons)
    assert report.circuit_breaker_active


def test_make_decision_fails_safe_when_unhealthy():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    # State has 20% drawdown breach
    state = StrategyState(
        cash_ledger=80_000.0,
        position_ledger={"AAPL": 0.05},
        strategy_peak_equity=100_000.0,
        current_equity=80_000.0,
    )

    snapshot = {"features": {"pred_AAPL": 0.10}, "symbols": ["AAPL"]}
    model_bundle = {"version": "v90_meta_confidence"}
    config = {"safety_config": {"max_strategy_drawdown_pct": 0.15}}

    output = make_decision(state, decision_ts, snapshot, model_bundle, config)

    # Must fail safe: new orders blocked, position retained as is
    assert not output.safety_report.is_safe
    assert len(output.approved_order_intents) == 0
    assert output.target_positions["AAPL"] == 0.05  # Retained
    assert output.risk_scale_applied == 0.0


def test_soft_drawdown_reduces_risk_scale_but_stays_safe():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={},
        strategy_peak_equity=100_000.0,
        current_equity=92_000.0,  # 8% DD → caution band
        last_quote_ts={},
    )
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"x": 1.0},
        config=SafetyConfig(
            caution_drawdown_pct=0.05,
            warning_drawdown_pct=0.10,
            max_strategy_drawdown_pct=0.15,
            caution_risk_scale=0.75,
            require_quotes_for_open_positions=False,
        ),
    )
    assert report.is_safe
    assert report.risk_scale == 0.75
    assert any("caution" in a.lower() for a in report.alerts)


def test_circuit_breaker_consecutive_losses():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={},
        consecutive_losses=5,
    )
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"x": 1.0},
        config=SafetyConfig(max_consecutive_losses=5, require_quotes_for_open_positions=False),
    )
    assert not report.is_safe
    assert report.circuit_breaker_active
    assert any("consecutive losses" in r for r in report.rejection_reasons)


def test_circuit_breaker_hourly_loss():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={},
        current_equity=94_000.0,
        hour_start_equity=100_000.0,  # -6% hourly
    )
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"x": 1.0},
        config=SafetyConfig(max_hourly_loss_pct=0.05, require_quotes_for_open_positions=False),
    )
    assert not report.is_safe
    assert any("hourly PnL" in r for r in report.rejection_reasons)


def test_wide_spread_blocks():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(cash_ledger=100_000.0, position_ledger={})
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={"quotes": {"AAPL": {"bid": 100.0, "ask": 105.0}}},  # 4.9% spread
        features={"x": 1.0},
        config=SafetyConfig(max_bid_ask_spread_pct=0.02, require_quotes_for_open_positions=False),
    )
    assert not report.is_safe
    assert any("Spread too wide" in r for r in report.rejection_reasons)


def test_sequence_gap_blocks():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={},
        last_sequence_num={"AAPL": 10},
    )
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={"sequence_nums": {"AAPL": 15}},  # gap of 5 > max 1
        features={"x": 1.0},
        config=SafetyConfig(max_sequence_gap=1, require_quotes_for_open_positions=False),
    )
    assert not report.is_safe
    assert any("Sequence gap" in r for r in report.rejection_reasons)


def test_notional_limit_blocks():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(cash_ledger=100_000.0, position_ledger={})
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"x": 1.0},
        config=SafetyConfig(
            max_single_order_notional_usd=50_000.0,
            require_quotes_for_open_positions=False,
        ),
        intended_orders_notional_usd={"AAPL": 80_000.0},
    )
    assert not report.is_safe
    assert any("Order notional" in r for r in report.rejection_reasons)


def test_kill_switch_blocks():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={},
        kill_switch=True,
        halted_reason="manual halt",
    )
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"x": 1.0},
        config=SafetyConfig(require_quotes_for_open_positions=False),
    )
    assert not report.is_safe
    assert any("Kill switch" in r for r in report.rejection_reasons)


def test_live_submission_disabled_in_live_mode():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(cash_ledger=100_000.0, position_ledger={})
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={"execution_mode": "LIVE"},
        features={"x": 1.0},
        config=SafetyConfig(
            allow_live_order_submission=False,
            require_quotes_for_open_positions=False,
        ),
    )
    assert not report.is_safe
    assert any("Live order submission disabled" in r for r in report.rejection_reasons)


def test_feature_zscore_anomaly():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(cash_ledger=100_000.0, position_ledger={})
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={"feature_baselines": {"mom": {"mean": 0.0, "std": 1.0}}},
        features={"mom": 20.0},
        config=SafetyConfig(max_feature_zscore=8.0, require_quotes_for_open_positions=False),
    )
    assert not report.is_safe
    assert any("Feature anomaly" in r for r in report.rejection_reasons)


def test_regime_risk_multiplier_high_vol_and_bear():
    assert regime_risk_multiplier("LOW", "UP", False) == 1.0
    assert regime_risk_multiplier("HIGH", "UP", False) == 0.50
    scale = regime_risk_multiplier("HIGH", "DOWN", True)
    assert scale == pytest.approx(0.50 * 0.60)  # bear overrides trend path after high vol


def test_make_decision_applies_regime_scale():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=1_000_000.0,
        position_ledger={},
        current_equity=1_000_000.0,
        strategy_peak_equity=1_000_000.0,
    )
    snapshot = {
        "features": {"pred_AAPL": 0.20},
        "symbols": ["AAPL"],
        "adv_usd": {"AAPL": 100_000_000.0},
        "sectors": {"AAPL": "Technology"},
        "regime": {"volatility_regime": "HIGH", "trend_regime": "UP", "bear_market": False},
        "execution_mode": "SHADOW",
    }
    model_bundle = {"version": "v90_meta_confidence"}
    config = {
        "safety_config": {
            "require_quotes_for_open_positions": False,
            "allow_live_order_submission": False,
        },
        "portfolio_limits": {"max_position_weight": 0.10},
    }
    output = make_decision(state, decision_ts, snapshot, model_bundle, config)
    assert output.safety_report.is_safe
    assert output.regime_scale_applied == 0.50
    # pred 0.20 * 0.50 = 0.10, clipped to max_position_weight 0.10
    assert abs(output.target_positions.get("AAPL", 0.0)) <= 0.10 + 1e-9


def test_walk_forward_gate_pass_and_fail():
    good = evaluate_walk_forward_gates([0.8, 1.1, 0.6, 0.9])
    assert good.passed
    bad = evaluate_walk_forward_gates([0.1, -0.5, 0.05])
    assert not bad.passed
    assert bad.reasons


def test_apply_regime_to_predictions():
    scaled, g = apply_regime_to_predictions(
        {"AAPL": 0.10, "MSFT": -0.08},
        volatility_regime="HIGH",
        bear_market=False,
    )
    assert g == 0.50
    assert scaled["AAPL"] == pytest.approx(0.05)
    assert scaled["MSFT"] == pytest.approx(-0.04)


def test_select_approved_model_version():
    candidates = [
        {"version": "v1", "fold_sharpes": [0.1, 0.0, -0.2]},
        {"version": "v2", "fold_sharpes": [0.9, 0.7, 0.8, 1.0]},
    ]
    assert select_approved_model_version(candidates) == "v2"


def test_broker_reconciliation_required():
    decision_ts = pd.Timestamp("2026-08-01 16:00:00")
    state = StrategyState(
        cash_ledger=100_000.0,
        position_ledger={"AAPL": 0.05},
        broker_positions={"AAPL": 0.01},
    )
    report = validate_live_safety_state(
        state=state,
        decision_ts=decision_ts,
        model_version="v90_meta_confidence",
        market_data={},
        features={"x": 1.0},
        config=SafetyConfig(
            require_broker_reconciliation=True,
            require_quotes_for_open_positions=False,
        ),
    )
    assert not report.is_safe
    assert any("Position discrepancy" in r for r in report.rejection_reasons)
