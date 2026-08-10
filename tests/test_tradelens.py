"""Unit tests for TradeLens and TradeLens++ evaluation framework."""
import pytest
import numpy as np
import pandas as pd

try:
    from edge.eval.tradelens import (
        decompose_tradelens,
        compute_tradelens_plus_plus,
        TradeLensDecompositionResult,
        TradeLensPlusPlusResult,
    )
except ImportError:
    from eval.tradelens import (
        decompose_tradelens,
        compute_tradelens_plus_plus,
        TradeLensDecompositionResult,
        TradeLensPlusPlusResult,
    )


def test_tradelens_basic_decomposition():
    portfolio_ret = np.array([0.01, 0.02, -0.005, 0.015, 0.01])
    market_ret = np.array([0.005, 0.01, 0.002, 0.008, 0.005])
    baseline_ret = np.array([0.008, 0.015, 0.000, 0.010, 0.007])
    c_total = 0.005
    c_dynamic = 0.002

    res = decompose_tradelens(
        portfolio_returns=portfolio_ret,
        market_returns=market_ret,
        baseline_selection_returns=baseline_ret,
        c_total=c_total,
        c_dynamic=c_dynamic,
    )

    assert isinstance(res, TradeLensDecompositionResult)
    # Check identity: P_gross == P_market + P_selection + P_timing
    assert pytest.approx(res.p_gross) == res.p_market + res.p_selection + res.p_timing
    assert pytest.approx(res.p_gross) == np.sum(portfolio_ret)
    assert pytest.approx(res.p_market) == np.sum(market_ret)
    assert pytest.approx(res.p_selection) == np.sum(baseline_ret - market_ret)
    assert pytest.approx(res.p_timing) == np.sum(portfolio_ret - baseline_ret)
    assert pytest.approx(res.r_system) == res.p_gross - c_total
    assert pytest.approx(res.r_agent) == res.p_timing - c_dynamic


def test_tradelens_plus_plus():
    portfolio_ret = np.array([0.02, 0.01, 0.015, -0.005, 0.01])
    counterfactual_ret = np.array([0.01, 0.01, 0.005, -0.005, 0.005])
    market_ret = np.array([0.005, 0.005, 0.005, -0.002, 0.002])

    res = compute_tradelens_plus_plus(
        portfolio_returns=portfolio_ret,
        counterfactual_baseline_returns=counterfactual_ret,
        market_returns=market_ret,
        c_llm=0.001,
        c_trading=0.001,
        c_infrastructure=0.0005,
    )

    assert isinstance(res, TradeLensPlusPlusResult)
    assert res.r_agent_counterfactual > 0
    assert res.agent_win_rate >= 0.5
    assert res.agent_value_ratio > 1.0
    assert res.is_agent_value_additive is True

    as_dict = res.as_dict()
    assert "betas" in as_dict
    assert "costs" in as_dict
    assert "agent_metrics" in as_dict
