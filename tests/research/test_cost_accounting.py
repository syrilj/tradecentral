"""Unit tests for Cost Accounting Module."""
import pytest
try:
    from edge.research.cost_accounting import (
        LLMCostModel,
        TradingFrictionModel,
        SystemInfrastructureCostModel,
        TotalDecisionCycleCost,
    )
except ImportError:
    from research.cost_accounting import (
        LLMCostModel,
        TradingFrictionModel,
        SystemInfrastructureCostModel,
        TotalDecisionCycleCost,
    )


def test_llm_cost_model():
    model = LLMCostModel(model_name="gpt-4o", tool_call_cost_usd=0.002)
    cost = model.calculate_cost(prompt_tokens=1000, completion_tokens=500, num_tool_calls=2)

    # 1000 input tokens * $2.50 / 1M = $0.0025
    # 500 output tokens * $10.00 / 1M = $0.005
    # 2 tool calls * $0.002 = $0.004
    # Total = 0.0025 + 0.005 + 0.004 = 0.0115
    assert pytest.approx(cost) == 0.0115


def test_trading_friction_model():
    model = TradingFrictionModel(commission_bps=2.5, half_spread_bps=2.5, slippage_bps=2.5)
    trade_res = model.calculate_trade_cost(trade_value_usd=100_000.0, adv_usd=10_000_000.0, daily_volatility=0.02)

    assert trade_res["fixed_bps"] == 7.5
    assert trade_res["impact_bps"] > 0.0
    assert trade_res["cost_usd"] > 75.0


def test_total_decision_cycle_cost():
    infra = SystemInfrastructureCostModel(cost_per_hour_usd=0.36)
    infra_cost = infra.calculate_cost(runtime_seconds=100)
    assert pytest.approx(infra_cost) == 0.01

    cycle_cost = TotalDecisionCycleCost(
        llm_cost_usd=0.05,
        trading_cost_usd=12.50,
        infrastructure_cost_usd=infra_cost,
    )
    assert cycle_cost.total_cost_usd == 12.56
